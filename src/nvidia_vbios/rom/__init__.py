"""Offline VBIOS images and normalized override bytes.

normalize(image, representation="ada-relocated-v1") explicitly selects the
closed reviewed AD107 recipe; "ada-relocated-v2" selects the experimental general
Ada relocation, which refuses any image it cannot fully verify;
"ampere-relocated-v1" selects the experimental GA102-GA107 export that drops the
EFI image and the bytes after the chain under the same rule; "turing-e0-end-v1"
selects the experimental Turing payload whose chain ends at its last data image.
Ordinary normalization keeps its existing behavior.
The recognized relocated runtime payload supports read-only inspection and
identity normalization. No hardware operation is performed.
"""
from .errors import FormatError, VbiosError
from .image import BiosImage, from_bytes, inspect, inspect_image, load, normalize

__all__ = ['BiosImage', 'FormatError', 'VbiosError', 'from_bytes', 'inspect',
           'inspect_image', 'load', 'normalize']
