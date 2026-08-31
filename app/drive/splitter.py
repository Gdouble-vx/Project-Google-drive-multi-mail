"""
File splitting and merging engine.
Splits large files into chunks that fit within individual drive quotas,
and reassembles them for download.
"""
import os
import io
import math
import hashlib
import logging
import tempfile
from typing import List, Tuple, Optional, BinaryIO

logger = logging.getLogger(__name__)

# Default chunk size: 10 GB
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024 * 1024

# Max single upload size (leave 1GB headroom from 15GB free tier)
MAX_SINGLE_CHUNK = 14 * 1024 * 1024 * 1024


class FileSplitter:
    """Handles splitting files for distributed storage and reassembling them."""

    @staticmethod
    def calculate_split(file_size: int, max_chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[dict]:
        """
        Calculate how to split a file. Returns list of chunk metadata.
        Each chunk info: {index, offset, size, md5 (placeholder)}
        """
        if file_size <= max_chunk_size:
            return [{
                "index": 0,
                "offset": 0,
                "size": file_size,
            }]

        num_chunks = math.ceil(file_size / max_chunk_size)
        chunks = []
        for i in range(num_chunks):
            offset = i * max_chunk_size
            size = min(max_chunk_size, file_size - offset)
            chunks.append({
                "index": i,
                "offset": offset,
                "size": size,
            })
        return chunks

    @staticmethod
    def split_file(file_obj: BinaryIO, max_chunk_size: int = DEFAULT_CHUNK_SIZE):
        """
        Generator that yields (chunk_data_bytes, chunk_index, md5_hash) tuples.
        Reads the file in chunks of max_chunk_size.
        """
        chunk_index = 0
        while True:
            data = file_obj.read(max_chunk_size)
            if not data:
                break
            md5 = hashlib.md5(data).hexdigest()
            yield data, chunk_index, md5
            chunk_index += 1

    @staticmethod
    def merge_chunks(chunk_streams: List[Tuple[int, BinaryIO]], output: BinaryIO) -> str:
        """
        Merge chunks back into the original file.
        chunk_streams: list of (chunk_index, stream) tuples, should be sorted by index.
        Returns the MD5 hash of the merged file.
        """
        md5 = hashlib.md5()
        for index, stream in sorted(chunk_streams, key=lambda x: x[0]):
            while True:
                data = stream.read(8 * 1024 * 1024)  # 8MB read buffer
                if not data:
                    break
                output.write(data)
                md5.update(data)
        return md5.hexdigest()

    @staticmethod
    def get_optimal_chunk_size(available_drives: List[int]) -> int:
        """
        Determine optimal chunk size based on available drive space.
        available_drives: list of available bytes per drive.
        """
        if not available_drives:
            return DEFAULT_CHUNK_SIZE

        min_drive = min(available_drives)
        # Use 90% of the smallest drive as chunk size, capped at 10GB
        optimal = int(min_drive * 0.9)
        optimal = min(optimal, DEFAULT_CHUNK_SIZE)
        optimal = max(optimal, 100 * 1024 * 1024)  # At least 100MB
        return optimal


class FileReassembler:
    """Reassembles split files from multiple drives."""

    @staticmethod
    def reassemble(chunks_with_streams: List[dict], output_path: str) -> str:
        """
        Reassemble file from chunks.
        chunks_with_streams: [{"index": int, "stream": BinaryIO}, ...]
        Returns: MD5 hash of reassembled file.
        """
        md5 = hashlib.md5()
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with open(output_path, "wb") as out:
            for chunk in sorted(chunks_with_streams, key=lambda c: c["index"]):
                stream = chunk["stream"]
                while True:
                    data = stream.read(8 * 1024 * 1024)
                    if not data:
                        break
                    out.write(data)
                    md5.update(data)

        return md5.hexdigest()
