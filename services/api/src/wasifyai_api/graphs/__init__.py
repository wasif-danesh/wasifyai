from wasifyai_platform_sdk import GraphRegistry

from wasifyai_api.graphs.hello import build_hello
from wasifyai_api.graphs.media_demo import build_media_demo


def default_registry() -> GraphRegistry:
    registry = GraphRegistry()
    registry.register("hello", build_hello)
    registry.register("media-demo", build_media_demo)
    registry.load_entry_points()  # installed product packages, e.g. wasifyai-music
    return registry
