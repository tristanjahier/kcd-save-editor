from argparse import ArgumentParser
from io import SEEK_END

def to_ascii_repr(data: bytes) -> str:
    """Render bytes as text; printable ASCII bytes as their char, others as the replacement character �."""
    return "".join(chr(b) if 0x20 <= b < 0x7F else "\ufffd" for b in data)

def to_uint_repr(data: bytes) -> str:
    """Decode bytes as an unsigned integer, stored in little-endian byte order."""
    return str(int.from_bytes(data, byteorder="little", signed=False))

def to_bool_repr(data: bytes) -> str:
    if len(data) != 1:
        raise ValueError("A boolean must be on a single byte.")

    if int.from_bytes(data) not in (0, 1):
        raise ValueError(f"A boolean byte must not contain any '1' bit apart from the least significant one. Allowed values are 00000000 and 00000001, got {data[0]:08b}.")

    return str(bool.from_bytes(data))

def to_string_table_repr(data: bytes) -> str:
    """Render bytes as a struct SStringTable."""
    if len(data) != 8:
        raise ValueError("An SStringTable structure must be on 8 bytes.")

    m_numStrings = data[:4]
    m_sizeStringData = data[4:]
    return f"{{m_numStrings: {to_uint_repr(m_numStrings)}, m_sizeStringData: {to_uint_repr(m_sizeStringData)}}}"

FOOTER_SIZE = 64  # in bytes

parser = ArgumentParser()
parser.add_argument("savefile")
args = parser.parse_args()

with open(args.savefile, "rb") as file:
    file.seek(-FOOTER_SIZE, SEEK_END)
    footer_bytes = file.read(FOOTER_SIZE)

print("All footer bytes, in hexadecimal:")
print(footer_bytes.hex(" "))

offset: int = 0  # the next byte offset

m_fileTypeCheck_size = 4
m_fileTypeCheck = footer_bytes[offset:offset+m_fileTypeCheck_size]
print(f"m_fileTypeCheck = '{to_ascii_repr(m_fileTypeCheck)}'")
offset += m_fileTypeCheck_size

m_MD5Signature_size = 16
m_MD5Signature = footer_bytes[offset:offset+m_MD5Signature_size]
print(f"m_MD5Signature = {m_MD5Signature.hex()}")
offset += m_MD5Signature_size

m_tags_size = 8
m_tags = footer_bytes[offset:offset+m_tags_size]
print(f"m_tags = {to_string_table_repr(m_tags)}")
offset += m_tags_size

m_attrNames_size = 8
m_attrNames = footer_bytes[offset:offset+m_attrNames_size]
print(f"m_attrNames = {to_string_table_repr(m_attrNames)}")
offset += m_attrNames_size

m_strData_size = 8
m_strData = footer_bytes[offset:offset+m_strData_size]
print(f"m_strData = {to_string_table_repr(m_strData)}")
offset += m_strData_size

m_numAttrSets_size = 4
m_numAttrSets = footer_bytes[offset:offset+m_numAttrSets_size]
print(f"m_numAttrSets = {to_uint_repr(m_numAttrSets)}")
offset += m_numAttrSets_size

m_sizeAttrSets_size = 4
m_sizeAttrSets = footer_bytes[offset:offset+m_sizeAttrSets_size]
print(f"m_sizeAttrSets = {to_uint_repr(m_sizeAttrSets)}")
offset += m_sizeAttrSets_size

m_sizeNodes_size = 4
m_sizeNodes = footer_bytes[offset:offset+m_sizeNodes_size]
print(f"m_sizeNodes = {to_uint_repr(m_sizeNodes)}")
offset += m_sizeNodes_size

m_numNodes_size = 4
m_numNodes = footer_bytes[offset:offset+m_numNodes_size]
print(f"m_numNodes = {to_uint_repr(m_numNodes)}")
offset += m_numNodes_size

m_hasInternalError_size = 1
m_hasInternalError = footer_bytes[offset:offset+m_hasInternalError_size]
print(f"m_hasInternalError = {to_bool_repr(m_hasInternalError)}")
offset += m_hasInternalError_size

trailing_padding_size = 3
trailing_padding = footer_bytes[offset:offset+trailing_padding_size]
print(f"trailing padding = {trailing_padding.hex(" ")}")
offset += trailing_padding_size

assert offset == FOOTER_SIZE
