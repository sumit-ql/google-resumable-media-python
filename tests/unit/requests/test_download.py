# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import io

import mock
import pytest
from six.moves import http_client

from google.resumable_media import common
import google.resumable_media.requests.download as download_mod


EXAMPLE_URL = (
    u'https://www.googleapis.com/download/storage/v1/b/'
    u'{BUCKET}/o/{OBJECT}?alt=media')


class TestDownload(object):

    @mock.patch(u'google.resumable_media.requests.download._LOGGER')
    def test__get_expected_md5_present(self, _LOGGER):
        download = download_mod.Download(EXAMPLE_URL)

        checksum = u'b2twdXNodGhpc2J1dHRvbg=='
        header_value = u'crc32c=3q2+7w==,md5={}'.format(checksum)
        headers = {download_mod._HASH_HEADER: header_value}
        response = _mock_response(headers=headers)

        expected_md5_hash = download._get_expected_md5(response)
        assert expected_md5_hash == checksum
        _LOGGER.info.assert_not_called()

    @mock.patch(u'google.resumable_media.requests.download._LOGGER')
    def test__get_expected_md5_missing(self, _LOGGER):
        download = download_mod.Download(EXAMPLE_URL)

        headers = {}
        response = _mock_response(headers=headers)

        expected_md5_hash = download._get_expected_md5(response)
        assert expected_md5_hash is None
        expected_msg = download_mod._MISSING_MD5.format(EXAMPLE_URL)
        _LOGGER.info.assert_called_once_with(expected_msg)

    def test__write_to_stream_no_hash_check(self):
        stream = io.BytesIO()
        download = download_mod.Download(EXAMPLE_URL, stream=stream)

        chunk1 = b'right now, '
        chunk2 = b'but a little later'
        response = _mock_response(chunks=[chunk1, chunk2], headers={})

        ret_val = download._write_to_stream(response)
        assert ret_val is None

        assert stream.getvalue() == chunk1 + chunk2

        # Check mocks.
        response.__enter__.assert_called_once_with()
        response.__exit__.assert_called_once_with(None, None, None)
        response.iter_content.assert_called_once_with(
            chunk_size=download_mod._SINGLE_GET_CHUNK_SIZE,
            decode_unicode=False)

    def test__write_to_stream_with_hash_check_success(self):
        stream = io.BytesIO()
        download = download_mod.Download(EXAMPLE_URL, stream=stream)

        chunk1 = b'first chunk, count starting at 0. '
        chunk2 = b'second chunk, or chunk 1, which is better? '
        chunk3 = b'ordinals and numerals and stuff.'
        header_value = u'crc32c=qmNCyg==,md5=fPAJHnnoi/+NadyNxT2c2w=='
        headers = {download_mod._HASH_HEADER: header_value}
        response = _mock_response(
            chunks=[chunk1, chunk2, chunk3], headers=headers)

        ret_val = download._write_to_stream(response)
        assert ret_val is None

        assert stream.getvalue() == chunk1 + chunk2 + chunk3

        # Check mocks.
        response.__enter__.assert_called_once_with()
        response.__exit__.assert_called_once_with(None, None, None)
        response.iter_content.assert_called_once_with(
            chunk_size=download_mod._SINGLE_GET_CHUNK_SIZE,
            decode_unicode=False)

    def test__write_to_stream_with_hash_check_fail(self):
        stream = io.BytesIO()
        download = download_mod.Download(EXAMPLE_URL, stream=stream)

        chunk1 = b'first chunk, count starting at 0. '
        chunk2 = b'second chunk, or chunk 1, which is better? '
        chunk3 = b'ordinals and numerals and stuff.'
        bad_checksum = u'd3JvbmcgbiBtYWRlIHVwIQ=='
        header_value = u'crc32c=V0FUPw==,md5={}'.format(bad_checksum)
        headers = {download_mod._HASH_HEADER: header_value}
        response = _mock_response(
            chunks=[chunk1, chunk2, chunk3], headers=headers)

        with pytest.raises(common.DataCorruption) as exc_info:
            download._write_to_stream(response)

        assert not download.finished

        error = exc_info.value
        assert error.response is response
        assert len(error.args) == 1
        good_checksum = u'fPAJHnnoi/+NadyNxT2c2w=='
        msg = download_mod._CHECKSUM_MISMATCH.format(
            EXAMPLE_URL, bad_checksum, good_checksum)
        assert error.args[0] == msg

        # Check mocks.
        response.__enter__.assert_called_once_with()
        response.__exit__.assert_called_once_with(None, None, None)
        response.iter_content.assert_called_once_with(
            chunk_size=download_mod._SINGLE_GET_CHUNK_SIZE,
            decode_unicode=False)

    def _consume_helper(
            self, stream=None, end=65536, user_agent=None, headers=None,
            chunks=(), response_headers=None):
        download = download_mod.Download(
            EXAMPLE_URL, stream=stream, end=end, user_agent=user_agent,
            headers=headers)
        transport = mock.Mock(spec=[u'request'])
        transport.request.return_value = _mock_response(
            chunks=chunks, headers=response_headers)

        assert not download.finished
        ret_val = download.consume(transport)
        assert ret_val is transport.request.return_value

        called_kwargs = {u'data': None, u'headers': download._headers}
        if chunks:
            assert stream is not None
            called_kwargs[u'stream'] = True
        transport.request.assert_called_once_with(
            u'GET', EXAMPLE_URL, **called_kwargs)

        range_bytes = u'bytes={:d}-{:d}'.format(0, end)
        assert download._headers[u'range'] == range_bytes
        assert download.finished

        return transport

    def test_consume(self):
        self._consume_helper()

    def test_consume_with_stream(self):
        stream = io.BytesIO()
        chunks = (b'up down ', b'charlie ', b'brown')
        transport = self._consume_helper(stream=stream, chunks=chunks)

        assert stream.getvalue() == b''.join(chunks)

        # Check mocks.
        response = transport.request.return_value
        response.__enter__.assert_called_once_with()
        response.__exit__.assert_called_once_with(None, None, None)
        response.iter_content.assert_called_once_with(
            chunk_size=download_mod._SINGLE_GET_CHUNK_SIZE,
            decode_unicode=False)

    def test_consume_with_stream_hash_check_success(self):
        stream = io.BytesIO()
        chunks = (b'up down ', b'charlie ', b'brown')
        header_value = u'md5=JvS1wjMvfbCXgEGeaJJLDQ=='
        headers = {download_mod._HASH_HEADER: header_value}
        transport = self._consume_helper(
            stream=stream, chunks=chunks, response_headers=headers)

        assert stream.getvalue() == b''.join(chunks)

        # Check mocks.
        response = transport.request.return_value
        response.__enter__.assert_called_once_with()
        response.__exit__.assert_called_once_with(None, None, None)
        response.iter_content.assert_called_once_with(
            chunk_size=download_mod._SINGLE_GET_CHUNK_SIZE,
            decode_unicode=False)

    def test_consume_with_stream_hash_check_fail(self):
        stream = io.BytesIO()
        download = download_mod.Download(
            EXAMPLE_URL, stream=stream)

        chunks = (b'zero zero', b'niner tango')
        bad_checksum = u'anVzdCBub3QgdGhpcyAxLA=='
        header_value = u'crc32c=V0FUPw==,md5={}'.format(bad_checksum)
        headers = {download_mod._HASH_HEADER: header_value}
        transport = mock.Mock(spec=[u'request'])
        transport.request.return_value = _mock_response(
            chunks=chunks, headers=headers)

        assert not download.finished
        with pytest.raises(common.DataCorruption) as exc_info:
            download.consume(transport)

        assert stream.getvalue() == b''.join(chunks)
        assert download.finished
        assert download._headers == {}

        error = exc_info.value
        assert error.response is transport.request.return_value
        assert len(error.args) == 1
        good_checksum = u'1A/dxEpys717C6FH7FIWDw=='
        msg = download_mod._CHECKSUM_MISMATCH.format(
            EXAMPLE_URL, bad_checksum, good_checksum)
        assert error.args[0] == msg

        # Check mocks.
        transport.request.assert_called_once_with(
            u'GET', EXAMPLE_URL, data=None, headers={}, stream=True)

    def test_consume_with_headers(self):
        headers = {}  # Empty headers
        end = 16383
        self._consume_helper(end=end, headers=headers)
        range_bytes = u'bytes={:d}-{:d}'.format(0, end)
        # Make sure the headers have been modified.
        assert headers == {u'range': range_bytes}

    def test_consume_with_user_agent(self):
        headers = {}
        end = 16383
        user_agent = "Custom-User-Agent-1.0"
        range_bytes = u'bytes={:d}-{:d}'.format(0, end)
        self._consume_helper(end=end, user_agent=user_agent, headers=headers)
        assert headers == {u'range': range_bytes, u'User-Agent': user_agent}


class TestChunkedDownload(object):

    @staticmethod
    def _response_content_range(start_byte, end_byte, total_bytes):
        return u'bytes {:d}-{:d}/{:d}'.format(
            start_byte, end_byte, total_bytes)

    def _response_headers(self, start_byte, end_byte, total_bytes):
        content_length = end_byte - start_byte + 1
        resp_range = self._response_content_range(
            start_byte, end_byte, total_bytes)
        return {
            u'content-length': u'{:d}'.format(content_length),
            u'content-range': resp_range,
        }

    def _mock_response(self, start_byte, end_byte, total_bytes,
                       content=None, status_code=None):
        response_headers = self._response_headers(
            start_byte, end_byte, total_bytes)
        return mock.Mock(
            content=content,
            headers=response_headers,
            status_code=status_code,
            spec=[
                u'content',
                u'headers',
                u'status_code',
            ],
        )

    def test_consume_next_chunk_already_finished(self):
        download = download_mod.ChunkedDownload(EXAMPLE_URL, 512, None)
        download._finished = True
        with pytest.raises(ValueError):
            download.consume_next_chunk(None)

    def _mock_transport(self, start, chunk_size, total_bytes, content=b''):
        transport = mock.Mock(spec=[u'request'])
        assert len(content) == chunk_size
        transport.request.return_value = self._mock_response(
            start, start + chunk_size - 1, total_bytes,
            content=content, status_code=int(http_client.OK))

        return transport

    def test_consume_next_chunk(self):
        start = 1536
        stream = io.BytesIO()
        data = b'Just one chunk.'
        chunk_size = len(data)
        download = download_mod.ChunkedDownload(
            EXAMPLE_URL, chunk_size, stream, start=start)
        total_bytes = 16384
        transport = self._mock_transport(
            start, chunk_size, total_bytes, content=data)

        # Verify the internal state before consuming a chunk.
        assert not download.finished
        assert download.bytes_downloaded == 0
        assert download.total_bytes is None
        # Actually consume the chunk and check the output.
        ret_val = download.consume_next_chunk(transport)
        assert ret_val is transport.request.return_value
        range_bytes = u'bytes={:d}-{:d}'.format(start, start + chunk_size - 1)
        download_headers = {u'range': range_bytes}
        transport.request.assert_called_once_with(
            u'GET', EXAMPLE_URL, data=None, headers=download_headers)
        assert stream.getvalue() == data
        # Go back and check the internal state after consuming the chunk.
        assert not download.finished
        assert download.bytes_downloaded == chunk_size
        assert download.total_bytes == total_bytes


class Test__parse_md5_header(object):

    CRC32C_CHECKSUM = u'3q2+7w=='
    MD5_CHECKSUM = u'c2l4dGVlbmJ5dGVzbG9uZw=='

    def test_empty_value(self):
        header_value = None
        response = None
        md5_header = download_mod._parse_md5_header(header_value, response)
        assert md5_header is None

    def test_crc32c_only(self):
        header_value = u'crc32c={}'.format(self.CRC32C_CHECKSUM)
        response = None
        md5_header = download_mod._parse_md5_header(header_value, response)
        assert md5_header is None

    def test_md5_only(self):
        header_value = u'md5={}'.format(self.MD5_CHECKSUM)
        response = None
        md5_header = download_mod._parse_md5_header(header_value, response)
        assert md5_header == self.MD5_CHECKSUM

    def test_both_crc32c_and_md5(self):
        header_value = u'crc32c={},md5={}'.format(
            self.CRC32C_CHECKSUM, self.MD5_CHECKSUM)
        response = None
        md5_header = download_mod._parse_md5_header(header_value, response)
        assert md5_header == self.MD5_CHECKSUM

    def test_md5_multiple_matches(self):
        another_checksum = u'eW91IGRpZCBXQVQgbm93Pw=='
        header_value = u'md5={},md5={}'.format(
            self.MD5_CHECKSUM, another_checksum)
        response = mock.sentinel.response

        with pytest.raises(common.InvalidResponse) as exc_info:
            download_mod._parse_md5_header(header_value, response)

        error = exc_info.value
        assert error.response is response
        assert len(error.args) == 3
        assert error.args[1] == header_value
        assert error.args[2] == [self.MD5_CHECKSUM, another_checksum]


def test__DoNothingHash():
    do_nothing_hash = download_mod._DoNothingHash()
    return_value = do_nothing_hash.update(b'some data')
    assert return_value is None


class Test__add_decoder(object):

    def test_non_gzipped(self):
        response_raw = mock.Mock(headers={}, spec=[u'headers'])
        md5_hash = download_mod._add_decoder(
            response_raw, mock.sentinel.md5_hash)

        assert md5_hash is mock.sentinel.md5_hash

    def test_gzipped(self):
        headers = {u'content-encoding': u'gzip'}
        response_raw = mock.Mock(
            headers=headers, spec=[u'headers', u'_decoder'])
        md5_hash = download_mod._add_decoder(
            response_raw, mock.sentinel.md5_hash)

        assert md5_hash is not mock.sentinel.md5_hash
        assert isinstance(md5_hash, download_mod._DoNothingHash)
        assert isinstance(response_raw._decoder, download_mod._GzipDecoder)
        assert response_raw._decoder._md5_hash is mock.sentinel.md5_hash


class Test_GzipDecoder(object):

    def test_constructor(self):
        decoder = download_mod._GzipDecoder(mock.sentinel.md5_hash)
        assert decoder._md5_hash is mock.sentinel.md5_hash

    def test_decompress(self):
        md5_hash = mock.Mock(spec=['update'])
        decoder = download_mod._GzipDecoder(md5_hash)

        data = b'\x1f\x8b\x08\x08'
        result = decoder.decompress(data)

        assert result == b''
        md5_hash.update.assert_called_once_with(data)


def _mock_response(status_code=http_client.OK, chunks=(), headers=None):
    if headers is None:
        headers = {}

    if chunks:
        mock_raw = mock.Mock(headers=headers, spec=[u'headers'])
        response = mock.MagicMock(
            headers=headers,
            status_code=int(status_code),
            raw=mock_raw,
            spec=[
                u'__enter__',
                u'__exit__',
                u'iter_content',
                u'status_code',
                u'headers',
                u'raw',
            ],
        )
        # i.e. context manager returns ``self``.
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        response.iter_content.return_value = iter(chunks)
        return response
    else:
        return mock.Mock(
            headers=headers,
            status_code=int(status_code),
            spec=[
                u'status_code',
                u'headers',
            ],
        )
