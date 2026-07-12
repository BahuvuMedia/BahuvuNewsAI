"""
BahuvuNewsAI - YouTube Uploader
===============================

Uploads a completed Bahuvu News video to YouTube, optionally sets a custom
thumbnail, and optionally adds the video to a playlist.

Pipeline position:

    video.video_composer
        + thumbnail.thumbnail_generator
        -> youtube.uploader

The built-in self-test is offline-safe and does not contact YouTube.

Run:

    python -m py_compile youtube/uploader.py
    python -m youtube.uploader

Required packages for real uploads:

    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2

Required Google setup:

1. Enable YouTube Data API v3 in a Google Cloud project.
2. Create OAuth 2.0 Desktop application credentials.
3. Download the credentials JSON file.
4. Save it as credentials/youtube_client_secret.json, or configure another path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import mimetypes
from pathlib import Path
import random
import re
import socket
import time
from typing import Any, Mapping, Protocol, Sequence


# =============================================================================
# ENUMS
# =============================================================================


class UploadStatus(str, Enum):
    VALIDATED = "validated"
    UPLOADED = "uploaded"
    FAILED = "failed"
    SKIPPED = "skipped"


class PrivacyStatus(str, Enum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(slots=True)
class YouTubeUploadConfig:
    client_secrets_path: Path = Path(
        "credentials/youtube_client_secret.json"
    )
    token_path: Path = Path("credentials/youtube_token.json")
    output_dir: Path = Path("outputs/youtube")
    manifest_filename: str = "upload_manifest.json"
    scopes: tuple[str, ...] = (
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
    )
    api_service_name: str = "youtube"
    api_version: str = "v3"
    chunk_size_bytes: int = 8 * 1024 * 1024
    maximum_retries: int = 8
    initial_retry_delay_seconds: float = 1.0
    write_manifest: bool = True
    open_browser: bool = True
    local_server_port: int = 0
    dry_run: bool = False
    thumbnail_max_bytes: int = 2 * 1024 * 1024

    def validate(self) -> None:
        if not self.scopes:
            raise ValueError("At least one OAuth scope is required.")
        if self.chunk_size_bytes <= 0:
            raise ValueError("Upload chunk size must be positive.")
        if self.maximum_retries < 0:
            raise ValueError("Maximum retries cannot be negative.")
        if self.initial_retry_delay_seconds < 0:
            raise ValueError("Retry delay cannot be negative.")
        if self.thumbnail_max_bytes <= 0:
            raise ValueError("Thumbnail size limit must be positive.")
        if not self.manifest_filename.strip():
            raise ValueError("Manifest filename cannot be empty.")


@dataclass(slots=True)
class YouTubeVideoMetadata:
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category_id: str = "25"
    privacy_status: PrivacyStatus = PrivacyStatus.PRIVATE
    default_language: str = "te"
    default_audio_language: str = "te"
    made_for_kids: bool = False
    embeddable: bool = True
    public_stats_viewable: bool = True
    publish_at: str = ""
    playlist_id: str = ""
    notify_subscribers: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        title = self.title.strip()
        if not title:
            raise ValueError("YouTube title cannot be empty.")
        if len(title) > 100:
            raise ValueError("YouTube title cannot exceed 100 characters.")
        if len(self.description) > 5000:
            raise ValueError(
                "YouTube description cannot exceed 5000 characters."
            )
        if not str(self.category_id).isdigit():
            raise ValueError("YouTube category ID must be numeric.")
        if self.publish_at and self.privacy_status != PrivacyStatus.PRIVATE:
            raise ValueError(
                "Scheduled publishing requires privacy status 'private'."
            )


@dataclass(slots=True)
class UploadRequest:
    video_path: Path
    metadata: YouTubeVideoMetadata
    thumbnail_path: Path | None = None
    bulletin_id: str = ""
    upload_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UploadResult:
    status: UploadStatus
    request: UploadRequest
    video_id: str = ""
    video_url: str = ""
    thumbnail_uploaded: bool = False
    playlist_added: bool = False
    manifest_path: Path | None = None
    upload_started_at: str = ""
    upload_completed_at: str = ""
    attempts: int = 0
    progress_percent: float = 0.0
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status in {
            UploadStatus.VALIDATED,
            UploadStatus.UPLOADED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "video_path": str(self.request.video_path),
            "thumbnail_path": (
                str(self.request.thumbnail_path)
                if self.request.thumbnail_path
                else None
            ),
            "bulletin_id": self.request.bulletin_id,
            "upload_id": self.request.upload_id,
            "metadata": {
                **asdict(self.request.metadata),
                "privacy_status": (
                    self.request.metadata.privacy_status.value
                ),
            },
            "video_id": self.video_id,
            "video_url": self.video_url,
            "thumbnail_uploaded": self.thumbnail_uploaded,
            "playlist_added": self.playlist_added,
            "manifest_path": (
                str(self.manifest_path) if self.manifest_path else None
            ),
            "upload_started_at": self.upload_started_at,
            "upload_completed_at": self.upload_completed_at,
            "attempts": self.attempts,
            "progress_percent": self.progress_percent,
            "error": self.error,
            "warnings": list(self.warnings),
            "success": self.success,
            "extra": dict(self.request.extra),
        }


@dataclass(slots=True)
class UploadSummary:
    processed: int = 0
    uploaded: int = 0
    validated: int = 0
    failed: int = 0
    skipped: int = 0

    @classmethod
    def from_results(
        cls,
        results: Sequence[UploadResult],
    ) -> "UploadSummary":
        return cls(
            processed=len(results),
            uploaded=sum(
                1 for item in results
                if item.status == UploadStatus.UPLOADED
            ),
            validated=sum(
                1 for item in results
                if item.status == UploadStatus.VALIDATED
            ),
            failed=sum(
                1 for item in results
                if item.status == UploadStatus.FAILED
            ),
            skipped=sum(
                1 for item in results
                if item.status == UploadStatus.SKIPPED
            ),
        )


# =============================================================================
# PROTOCOLS AND HELPERS
# =============================================================================


class YouTubeServiceProtocol(Protocol):
    def videos(self) -> Any:
        ...

    def thumbnails(self) -> Any:
        ...

    def playlistItems(self) -> Any:
        ...


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _slugify(value: str, fallback: str = "upload") -> str:
    value = re.sub(r"[^\w\-]+", "_", value.strip().lower(), flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def coerce_video_metadata(value: Any) -> YouTubeVideoMetadata:
    if isinstance(value, YouTubeVideoMetadata):
        return value

    mapping = _coerce_mapping(value)
    if not mapping:
        raise TypeError(
            "Video metadata must be a mapping, dataclass, or object."
        )

    privacy_value = mapping.get("privacy_status") or "private"
    if isinstance(privacy_value, PrivacyStatus):
        privacy = privacy_value
    else:
        privacy = PrivacyStatus(str(privacy_value).strip().lower())

    tags_value = mapping.get("tags") or []
    if isinstance(tags_value, str):
        tags = [
            item.strip()
            for item in tags_value.split(",")
            if item.strip()
        ]
    else:
        tags = [
            _safe_text(item).strip()
            for item in tags_value
            if _safe_text(item).strip()
        ]

    metadata = mapping.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    return YouTubeVideoMetadata(
        title=_safe_text(mapping.get("title") or ""),
        description=_safe_text(mapping.get("description") or ""),
        tags=tags,
        category_id=_safe_text(mapping.get("category_id") or "25"),
        privacy_status=privacy,
        default_language=_safe_text(
            mapping.get("default_language") or "te"
        ),
        default_audio_language=_safe_text(
            mapping.get("default_audio_language") or "te"
        ),
        made_for_kids=bool(mapping.get("made_for_kids", False)),
        embeddable=bool(mapping.get("embeddable", True)),
        public_stats_viewable=bool(
            mapping.get("public_stats_viewable", True)
        ),
        publish_at=_safe_text(mapping.get("publish_at") or ""),
        playlist_id=_safe_text(mapping.get("playlist_id") or ""),
        notify_subscribers=bool(
            mapping.get("notify_subscribers", False)
        ),
        metadata=dict(metadata),
    )


# =============================================================================
# UPLOADER
# =============================================================================


class YouTubeUploader:
    RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
    RETRIABLE_EXCEPTIONS = (
        ConnectionError,
        TimeoutError,
        socket.timeout,
    )

    def __init__(
        self,
        config: YouTubeUploadConfig | None = None,
        service: YouTubeServiceProtocol | None = None,
    ) -> None:
        self.config = config or YouTubeUploadConfig()
        self.config.validate()
        self._service = service

    def dependencies_available(self) -> bool:
        try:
            import googleapiclient.discovery  # noqa: F401
            import google_auth_oauthlib.flow  # noqa: F401
            import google.oauth2.credentials  # noqa: F401
            return True
        except ImportError:
            return False

    def authenticate(self) -> YouTubeServiceProtocol:
        if self._service is not None:
            return self._service

        if not self.dependencies_available():
            raise RuntimeError(
                "Google API packages are not installed. Run: "
                "pip install google-api-python-client "
                "google-auth-oauthlib google-auth-httplib2"
            )

        if not self.config.client_secrets_path.exists():
            raise FileNotFoundError(
                "YouTube OAuth client secrets file not found: "
                f"{self.config.client_secrets_path}"
            )

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        credentials = None

        if self.config.token_path.exists():
            credentials = Credentials.from_authorized_user_file(
                str(self.config.token_path),
                list(self.config.scopes),
            )

        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.config.client_secrets_path),
                list(self.config.scopes),
            )
            credentials = flow.run_local_server(
                port=self.config.local_server_port,
                open_browser=self.config.open_browser,
                access_type="offline",
                prompt="consent",
            )

        self.config.token_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.config.token_path.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

        self._service = build(
            self.config.api_service_name,
            self.config.api_version,
            credentials=credentials,
            cache_discovery=False,
        )
        return self._service

    def validate_request(self, request: UploadRequest) -> list[str]:
        warnings: list[str] = []
        request.metadata.validate()

        if not request.video_path.exists():
            raise FileNotFoundError(
                f"Video file not found: {request.video_path}"
            )
        if not request.video_path.is_file():
            raise ValueError("Video path must identify a file.")
        if request.video_path.stat().st_size <= 0:
            raise ValueError("Video file is empty.")
        if request.video_path.suffix.lower() not in {
            ".mp4",
            ".mov",
            ".m4v",
            ".avi",
            ".webm",
        }:
            warnings.append(
                "The video extension is unusual for YouTube upload."
            )

        if request.thumbnail_path is not None:
            if not request.thumbnail_path.exists():
                raise FileNotFoundError(
                    "Thumbnail file not found: "
                    f"{request.thumbnail_path}"
                )
            if request.thumbnail_path.stat().st_size > (
                self.config.thumbnail_max_bytes
            ):
                raise ValueError(
                    "Thumbnail exceeds the configured 2 MB limit."
                )
            if request.thumbnail_path.suffix.lower() not in {
                ".jpg",
                ".jpeg",
                ".png",
            }:
                raise ValueError(
                    "Thumbnail must be a JPEG or PNG image."
                )

        if len(request.metadata.tags) > 30:
            warnings.append(
                "A large number of tags was supplied."
            )

        return warnings

    def upload(
        self,
        *,
        video_path: str | Path,
        metadata: YouTubeVideoMetadata | Mapping[str, Any],
        thumbnail_path: str | Path | None = None,
        bulletin_id: str = "",
        upload_id: str = "",
        extra: Mapping[str, Any] | None = None,
        dry_run: bool | None = None,
    ) -> UploadResult:
        request = UploadRequest(
            video_path=Path(video_path),
            thumbnail_path=(
                Path(thumbnail_path) if thumbnail_path else None
            ),
            metadata=coerce_video_metadata(metadata),
            bulletin_id=bulletin_id,
            upload_id=upload_id,
            extra=dict(extra or {}),
        )

        started_at = _utc_now_iso()
        warnings: list[str] = []

        try:
            warnings.extend(self.validate_request(request))
            effective_dry_run = (
                self.config.dry_run
                if dry_run is None
                else dry_run
            )

            if effective_dry_run:
                result = UploadResult(
                    status=UploadStatus.VALIDATED,
                    request=request,
                    manifest_path=self._manifest_path(request),
                    upload_started_at=started_at,
                    upload_completed_at=_utc_now_iso(),
                    attempts=0,
                    progress_percent=0.0,
                    warnings=warnings + [
                        "Dry run completed; no YouTube API call was made."
                    ],
                )
                if self.config.write_manifest:
                    self.write_manifest(result)
                return result

            service = self.authenticate()
            video_id, attempts = self._upload_video(
                service,
                request,
            )

            thumbnail_uploaded = False
            playlist_added = False

            if request.thumbnail_path:
                self._set_thumbnail(
                    service,
                    video_id,
                    request.thumbnail_path,
                )
                thumbnail_uploaded = True

            if request.metadata.playlist_id:
                self._add_to_playlist(
                    service,
                    video_id,
                    request.metadata.playlist_id,
                )
                playlist_added = True

            result = UploadResult(
                status=UploadStatus.UPLOADED,
                request=request,
                video_id=video_id,
                video_url=f"https://www.youtube.com/watch?v={video_id}",
                thumbnail_uploaded=thumbnail_uploaded,
                playlist_added=playlist_added,
                manifest_path=self._manifest_path(request),
                upload_started_at=started_at,
                upload_completed_at=_utc_now_iso(),
                attempts=attempts,
                progress_percent=100.0,
                warnings=warnings,
            )

            if self.config.write_manifest:
                self.write_manifest(result)

            return result

        except Exception as exc:
            result = UploadResult(
                status=UploadStatus.FAILED,
                request=request,
                upload_started_at=started_at,
                upload_completed_at=_utc_now_iso(),
                error=str(exc),
                warnings=warnings,
            )
            return result

    def _upload_video(
        self,
        service: YouTubeServiceProtocol,
        request: UploadRequest,
    ) -> tuple[str, int]:
        from googleapiclient.http import MediaFileUpload

        body = self._build_video_resource(request.metadata)
        media = MediaFileUpload(
            str(request.video_path),
            chunksize=self.config.chunk_size_bytes,
            resumable=True,
            mimetype=(
                mimetypes.guess_type(request.video_path.name)[0]
                or "video/*"
            ),
        )

        insert_request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
            notifySubscribers=request.metadata.notify_subscribers,
        )

        response = None
        attempts = 0

        while response is None:
            try:
                attempts += 1
                _, response = insert_request.next_chunk()

            except Exception as exc:
                status = getattr(
                    getattr(exc, "resp", None),
                    "status",
                    None,
                )

                retriable = (
                    status in self.RETRIABLE_STATUS_CODES
                    or isinstance(exc, self.RETRIABLE_EXCEPTIONS)
                )

                if not retriable or attempts > self.config.maximum_retries:
                    raise

                delay = self._retry_delay(attempts)
                time.sleep(delay)

        video_id = _safe_text(response.get("id"))
        if not video_id:
            raise RuntimeError(
                "YouTube upload completed without returning a video ID."
            )

        return video_id, attempts

    def _set_thumbnail(
        self,
        service: YouTubeServiceProtocol,
        video_id: str,
        thumbnail_path: Path,
    ) -> None:
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(
            str(thumbnail_path),
            mimetype=(
                mimetypes.guess_type(thumbnail_path.name)[0]
                or "application/octet-stream"
            ),
            resumable=False,
        )
        service.thumbnails().set(
            videoId=video_id,
            media_body=media,
        ).execute()

    def _add_to_playlist(
        self,
        service: YouTubeServiceProtocol,
        video_id: str,
        playlist_id: str,
    ) -> None:
        service.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        ).execute()

    def _build_video_resource(
        self,
        metadata: YouTubeVideoMetadata,
    ) -> dict[str, Any]:
        snippet: dict[str, Any] = {
            "title": metadata.title.strip(),
            "description": metadata.description,
            "tags": metadata.tags,
            "categoryId": str(metadata.category_id),
            "defaultLanguage": metadata.default_language,
            "defaultAudioLanguage": metadata.default_audio_language,
        }

        status: dict[str, Any] = {
            "privacyStatus": metadata.privacy_status.value,
            "selfDeclaredMadeForKids": metadata.made_for_kids,
            "embeddable": metadata.embeddable,
            "publicStatsViewable": metadata.public_stats_viewable,
        }

        if metadata.publish_at:
            status["publishAt"] = metadata.publish_at

        return {
            "snippet": snippet,
            "status": status,
        }

    def _retry_delay(self, attempt: int) -> float:
        maximum = (
            self.config.initial_retry_delay_seconds
            * (2 ** max(0, attempt - 1))
        )
        return random.uniform(0.0, maximum)

    def _manifest_path(
        self,
        request: UploadRequest,
    ) -> Path:
        name = _slugify(
            request.bulletin_id
            or request.upload_id
            or request.video_path.stem
        )
        return (
            self.config.output_dir
            / name
            / self.config.manifest_filename
        )

    def write_manifest(self, result: UploadResult) -> Path:
        if result.manifest_path is None:
            result.manifest_path = self._manifest_path(result.request)

        result.manifest_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        result.manifest_path.write_text(
            json.dumps(
                result.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return result.manifest_path

    def summarize(
        self,
        results: Sequence[UploadResult],
    ) -> UploadSummary:
        return UploadSummary.from_results(results)


# =============================================================================
# OFFLINE-SAFE SELF-TEST
# =============================================================================


def _run_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(
        prefix="bahuvu_youtube_uploader_test_"
    ) as temp_dir:
        root = Path(temp_dir)
        video_path = root / "bulletin.mp4"
        thumbnail_path = root / "thumbnail.png"

        video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 1024)
        thumbnail_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 1024)

        config = YouTubeUploadConfig(
            output_dir=root / "youtube",
            dry_run=True,
            write_manifest=True,
        )
        uploader = YouTubeUploader(config=config)

        metadata = YouTubeVideoMetadata(
            title="బాహువు న్యూస్ జూలై 2026 ప్రధాన వార్తలు",
            description="జూలై 2026 నెలలోని ముఖ్యమైన తెలుగు వార్తల సమాహారం.",
            tags=["Bahuvu News", "Telugu News", "July 2026"],
            category_id="25",
            privacy_status=PrivacyStatus.PRIVATE,
            default_language="te",
            default_audio_language="te",
            made_for_kids=False,
            playlist_id="PL_TEST_PLAYLIST",
        )

        resource = uploader._build_video_resource(metadata)
        assert resource["snippet"]["categoryId"] == "25"
        assert resource["status"]["privacyStatus"] == "private"
        assert resource["status"]["selfDeclaredMadeForKids"] is False

        result = uploader.upload(
            video_path=video_path,
            thumbnail_path=thumbnail_path,
            metadata=metadata,
            bulletin_id="bahuvu_july_2026",
        )

        assert result.status == UploadStatus.VALIDATED
        assert result.success
        assert result.video_id == ""
        assert result.video_url == ""
        assert result.manifest_path is not None
        assert result.manifest_path.exists()
        assert result.request.video_path == video_path
        assert result.request.thumbnail_path == thumbnail_path

        loaded = json.loads(
            result.manifest_path.read_text(encoding="utf-8")
        )
        assert loaded["status"] == "validated"
        assert loaded["success"] is True
        assert loaded["metadata"]["privacy_status"] == "private"
        assert loaded["metadata"]["title"] == metadata.title

        mapped = coerce_video_metadata(
            {
                "title": "Test Upload",
                "privacy_status": "unlisted",
                "tags": "one, two, three",
            }
        )
        assert mapped.privacy_status == PrivacyStatus.UNLISTED
        assert mapped.tags == ["one", "two", "three"]

        summary = uploader.summarize([result])
        assert summary.processed == 1
        assert summary.validated == 1
        assert summary.failed == 0

        print("YouTube uploader initialized successfully.")
        print()
        print(f"Video validated         : {result.request.video_path.exists()}")
        print(
            f"Thumbnail validated     : "
            f"{result.request.thumbnail_path.exists()}"
        )
        print(
            f"Privacy status          : "
            f"{result.request.metadata.privacy_status.value}"
        )
        print(f"Playlist configured     : {bool(metadata.playlist_id)}")
        print(f"Dry-run status          : {result.status.value}")
        print(f"Manifest written        : {result.manifest_path.exists()}")
        print(
            f"Google dependencies     : "
            f"{uploader.dependencies_available()}"
        )
        print()
        print("YouTube uploader self-test passed.")


if __name__ == "__main__":
    _run_self_test()