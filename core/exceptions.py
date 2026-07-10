"""
BahuvuNewsAI
core/exceptions.py

Custom exception hierarchy for the BahuvuNewsAI project.

All project-specific errors should inherit from BahuvuError.
"""


class BahuvuError(Exception):
    """
    Base class for all project exceptions.
    """


class ConfigurationError(BahuvuError):
    """
    Raised when configuration is missing or invalid.
    """


class PipelineError(BahuvuError):
    """
    Raised when the pipeline cannot continue.
    """


class ValidationError(BahuvuError):
    """
    Raised when editorial validation fails.
    """


class DownloadError(BahuvuError):
    """
    Raised when downloading content or media fails.
    """


class FactCheckError(BahuvuError):
    """
    Raised when fact checking cannot be completed.
    """


class DuplicateContentError(BahuvuError):
    """
    Raised when duplicate news content is detected.
    """


class TranslationError(BahuvuError):
    """
    Raised when translation fails.
    """


class VoiceGenerationError(BahuvuError):
    """
    Raised when voice generation fails.
    """


class GraphicsGenerationError(BahuvuError):
    """
    Raised when graphics generation fails.
    """


class VideoGenerationError(BahuvuError):
    """
    Raised when video composition fails.
    """


class PublishingError(BahuvuError):
    """
    Raised when publishing to an external platform fails.
    """


class MetadataError(BahuvuError):
    """
    Raised when metadata generation fails.
    """


# ------------------------------------------------------------------
# Self Test
# ------------------------------------------------------------------

if __name__ == "__main__":

    try:
        raise ValidationError("Sample validation failure")

    except BahuvuError as exc:
        print(f"Exception hierarchy working: {exc}")