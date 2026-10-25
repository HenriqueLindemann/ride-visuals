"""Canonical CLI choice values shared by related commands."""

LOCALES = ("en", "pt-BR")
THEMES = ("midnight", "frost")
MAP_DETAILS = ("standard", "high")
MAP_ROUTE_STYLES = ("orange", "monochrome", "monthly")
COLLECTION_MOTIONS = ("simultaneous", "elapsed", "chronological", "comet")
COLLECTION_STYLES = (
    "orange",
    "density",
    "monochrome",
    "monthly",
    "heart_rate",
    "temperature",
    "altitude",
    "speed",
    "grade",
)
VIDEO_ASPECTS = ("16:9", "9:16", "instagram", "4k")
SCENE3D_LOOKS = ("carbon", "satellite")
STRATA_PERIODS = ("auto", "month", "year")
SCENE3D_TYPES = ("flyover", "stretch", "strata", "territory", "ascent")
VIDEO_TYPES = (
    "clean",
    "telemetry",
    "minimal",
    "overlay",
    "route-overlay",
    "stats-overlay",
    "progress",
    "collection",
    "timeline",
    *SCENE3D_TYPES,
)
OVERLAY_FORMATS = ("png", "webm", "mov")
