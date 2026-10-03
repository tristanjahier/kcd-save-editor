meta:
  id: kcd_whs
  title: Kingdom Come Deliverance (1) save file (.whs) container
  application: "Kingdom Come: Deliverance (Warhorse Studios, CryEngine)"
  file-extension: whs
  ks-version: '0.10'
  endian: le
doc: |
  On-disk container of a Kingdom Come: Deliverance (1) save: CryEngine's
  XMLCPB compressed writer. The data is cut into 32 KiB blocks, each
  compressed with zlib (level 3), followed by a 64-byte footer holding an MD5
  of the whole file (computed with the `md5` field zeroed).

  This spec shows each block decompressed, but the save format itself spans
  block boundaries: decompress the whole file with `whs_decompress.py` and
  read the result with kcd_save_payload.ksy.
seq:
  - id: blocks
    type: block
    repeat: until
    repeat-until: _io.pos >= _io.size - 64
  - id: footer
    type: footer
types:
  block:
    seq:
      - id: len_compressed
        type: u4
        doc: 0xFFFFFFFF means the block is stored uncompressed (never seen).
      - id: len_uncompressed
        type: u4
        doc: 32768 for every block but the last.
      - id: data
        size: len_compressed
        process: zlib
        if: len_compressed != 0xffffffff
      - id: data_raw
        size: len_uncompressed
        if: len_compressed == 0xffffffff
  footer:
    doc: |
      CryEngine XMLCPB::SFileHeader, written at the end of the file. KCD does
      not use the XMLCPB tables, so all the counts below are 0.
    seq:
      - id: magic
        contents: [0x30, 0x58, 0x42, 0x50]
        doc: "'PBX0' as a little-endian u4."
      - id: md5
        size: 16
      - id: num_tags
        type: u4
      - id: len_tags
        type: u4
      - id: num_attr_names
        type: u4
      - id: len_attr_names
        type: u4
      - id: num_str_data
        type: u4
      - id: len_str_data
        type: u4
      - id: num_attr_sets
        type: u4
      - id: len_attr_sets
        type: u4
      - id: len_nodes
        type: u4
      - id: num_nodes
        type: u4
      - id: has_internal_error
        type: u1
      - id: padding
        size: 3
