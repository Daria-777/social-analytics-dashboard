from enum import StrEnum


class Platform(StrEnum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"


class ContentType(StrEnum):
    VIDEO = "video"
    REEL = "reel"
    PHOTO = "photo"
    CAROUSEL = "carousel"
    STORY = "story"
    OTHER = "other"


class Source(StrEnum):
    INSTAGRAM_API = "instagram_api"
    INSTAGRAM_UI = "instagram_ui"
    TIKTOK_API = "tiktok_api"
    TIKTOK_STUDIO = "tiktok_studio"
    MANUAL = "manual"


class DataStatus(StrEnum):
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    UNAVAILABLE = "unavailable"
    ANOMALOUS = "anomalous"
    ESTIMATED = "estimated"
    MANUAL = "manual"


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"


class CollectorStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
