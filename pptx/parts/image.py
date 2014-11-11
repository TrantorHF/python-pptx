# encoding: utf-8

"""
ImagePart and related objects.
"""

import hashlib
import os
import posixpath

try:
    from PIL import Image as PIL_Image
except ImportError:
    import Image as PIL_Image

from StringIO import StringIO

from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from pptx.opc.spec import image_content_types
from pptx.parts.part import PartCollection
from pptx.util import lazyproperty, Px


class ImagePart(Part):
    """
    An image part, generally having a partname matching the regex
    ``ppt/media/image[1-9][0-9]*.*``.
    """
    def __init__(self, partname, content_type, blob, ext, filename=None):
        super(ImagePart, self).__init__(partname, content_type, blob)
        self._ext = ext
        self._filename = filename

    @classmethod
    def new(cls, partname, image_file):
        """
        Return a new |ImagePart| instance loaded from *img_file*, which may
        be a path to a file (a string), or a file-like object. *partname* is
        assigned to the new image part.
        """
        filename, ext, content_type, blob = cls._load_from_file(image_file)
        return cls(partname, content_type, blob, ext, filename)

    @property
    def ext(self):
        """
        Return file extension for this image e.g. ``'png'``.
        """
        return self._ext

    @classmethod
    def load(cls, partname, content_type, blob, package):
        ext = posixpath.splitext(partname)[1]
        return cls(partname, content_type, blob, ext)

    def scale(self, width, height):
        """
        Return scaled image dimensions based on supplied parameters. If
        *width* and *height* are both |None|, the native image size is
        returned. If neither *width* nor *height* is |None|, their values are
        returned unchanged. If a value is provided for either *width* or
        *height* and the other is |None|, the dimensions are scaled,
        preserving the image's aspect ratio.
        """
        native_width_px, native_height_px = self._size
        native_width = Px(native_width_px)
        native_height = Px(native_height_px)

        if width is None and height is None:
            width = native_width
            height = native_height
        elif width is None:
            scaling_factor = float(height) / float(native_height)
            width = int(round(native_width * scaling_factor))
        elif height is None:
            scaling_factor = float(width) / float(native_width)
            height = int(round(native_height * scaling_factor))
        return width, height

    @lazyproperty
    def sha1(self):
        """
        The SHA1 hash digest for the image binary of this image part, like:
        ``'1be010ea47803b00e140b852765cdf84f491da47'``.
        """
        return hashlib.sha1(self._blob).hexdigest()

    @property
    def _desc(self):
        """
        Return filename associated with this image, either the filename of
        the original image file the image was created with or a synthetic
        name of the form ``image.ext`` where ``ext`` is appropriate to the
        image file format, e.g. ``'jpg'``.
        """
        # return generic filename if original filename is unknown
        if self._filename is None:
            return 'image.%s' % self.ext
        return self._filename

    @staticmethod
    def _ext_from_image_stream(stream):
        """
        Return the filename extension appropriate to the image file contained
        in *stream*.
        """
        ext_map = {
            'BMP': 'bmp', 'GIF': 'gif', 'JPEG': 'jpg', 'PNG': 'png',
            'TIFF': 'tiff', 'WMF': 'wmf'
        }
        stream.seek(0)
        format = PIL_Image.open(stream).format
        if format not in ext_map:
            tmpl = "unsupported image format, expected one of: %s, got '%s'"
            raise ValueError(tmpl % (ext_map.keys(), format))
        return ext_map[format]

    @staticmethod
    def _image_ext_content_type(ext):
        """
        Return the content type corresponding to filename extension *ext*
        """
        key = ext.lower()
        if key not in image_content_types:
            tmpl = "unsupported image file extension '%s'"
            raise ValueError(tmpl % (ext))
        content_type = image_content_types[key]
        return content_type

    @classmethod
    def _load_from_file(cls, image_file):
        """
        Return a (path, ext, content_type, blob) 4-tuple for the image
        located in *image_file*, which may be either a path to an image file
        or a file-like object.
        """
        if isinstance(image_file, basestring):  # image_file is a path
            path = image_file
            filename = os.path.split(path)[1]
            ext = os.path.splitext(path)[1][1:]
            content_type = cls._image_ext_content_type(ext)
            with open(path, 'rb') as f:
                blob = f.read()
        else:  # assume image_file is a file-like object
            filename = None
            ext = cls._ext_from_image_stream(image_file)
            content_type = cls._image_ext_content_type(ext)
            image_file.seek(0)
            blob = image_file.read()
        return filename, ext, content_type, blob

    @property
    def _size(self):
        """
        Return *width*, *height* tuple representing native dimensions of
        image in pixels.
        """
        image_stream = StringIO(self._blob)
        width_px, height_px = PIL_Image.open(image_stream).size
        image_stream.close()
        return width_px, height_px


class ImageCollection(PartCollection):
    """
    Immutable sequence of images, typically belonging to an instance of
    |Package|. An image part containing a particular image blob appears only
    once in an instance, regardless of how many times it is referenced by a
    pic shape in a slide.
    """
    def __init__(self):
        super(ImageCollection, self).__init__()

    def add_image(self, file):
        """
        Return image part containing the image in *file*, which is either a
        path to an image file or a file-like object containing an image. If an
        image instance containing this same image already exists, that
        instance is returned. If it does not yet exist, a new one is created.
        """
        # use Image constructor to validate and characterize image file
        partname = PackURI('/ppt/media/image1.jpeg')  # dummy just for baseURI
        image = ImagePart.new(partname, file)
        # return matching image if found
        for existing_image in self._values:
            if existing_image.sha1 == image.sha1:
                return existing_image
        # otherwise add it to collection and return new image
        self._values.append(image)
        self._rename_images()
        return image

    def load(self, parts):
        """
        Load the image collection with all the image parts in iterable
        *parts*.
        """
        def is_image_part(part):
            return (
                isinstance(part, ImagePart) and
                part.partname.startswith('/ppt/media/')
            )
        for part in parts:
            if is_image_part(part):
                self.add_part(part)

    def _rename_images(self):
        """
        Assign partnames like ``/ppt/media/image9.png`` to all images in the
        collection. The name portion is always ``image``. The number part
        forms a continuous sequence starting at 1 (e.g. 1, 2, 3, ...). The
        extension is preserved during renaming.
        """
        for idx, image in enumerate(self._values):
            partname_str = '/ppt/media/image%d.%s' % (idx+1, image.ext)
            image.partname = PackURI(partname_str)
