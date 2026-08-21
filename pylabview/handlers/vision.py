from __future__ import annotations

from ..typesystem import ErrorCluster
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


@registry.register("image_read")
def image_read(context: HandlerContext):
    return context.runtime.vision.read(context.runtime._safe_path(context.node))


@registry.register("camera_capture")
def camera_capture(context: HandlerContext):
    return context.runtime.vision.capture(int(context.node.properties.get("camera_index", 0)))


@registry.register("image_grayscale", "image_blur", "image_threshold", "image_canny", "image_resize")
def image_operator(context: HandlerContext):
    vision, image, properties = context.runtime.vision, context.inputs["image"], context.node.properties
    operations = {
        "image_grayscale": lambda: vision.grayscale(image),
        "image_blur": lambda: vision.blur(image, int(properties.get("kernel", 5))),
        "image_threshold": lambda: vision.threshold(image, properties.get("threshold", 127), properties.get("maximum", 255)),
        "image_canny": lambda: vision.canny(image, properties.get("low", 50), properties.get("high", 150)),
        "image_resize": lambda: vision.resize(image, properties.get("width", 640), properties.get("height", 480)),
    }
    return operations[context.node.type]()


@registry.register("template_match")
def template_match(context: HandlerContext):
    return context.runtime.vision.template_match(context.inputs["image"], context.inputs["template"])


@registry.register("image_save")
def image_save(context: HandlerContext):
    try:
        context.runtime.vision.save(context.inputs["image"], context.runtime._safe_path(context.node))
        return ErrorCluster()
    except (OSError, ValueError, RuntimeError) as exc:
        return ErrorCluster(True, 40, str(exc))
