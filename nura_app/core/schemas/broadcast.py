"""Validated admin contracts for the minimal Telegram campaign contour."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CampaignType = Literal["editorial", "commercial"]
SegmentType = Literal[
    "all_editorial_enabled",
    "mini_completed_without_full_purchase",
    "full_report_purchasers",
    "onboarding_incomplete",
    "inactive",
]
Destination = Literal[
    "main_menu",
    "chat",
    "tarot_daily",
    "my_reports",
    "buy_matrix",
    "profile",
    "settings",
]
MediaType = Literal["photo", "animation", "video"]


class BroadcastCTA(BaseModel):
    key: Literal["primary", "secondary"]
    label: str = Field(min_length=1, max_length=64)
    destination: Destination

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("cta_label_required")
        return normalized


class CampaignContent(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    media_type: MediaType | None = None
    media_file_id: str | None = Field(default=None, min_length=1, max_length=256)
    ctas: list[BroadcastCTA] = Field(min_length=1, max_length=2)
    segment_type: SegmentType
    segment_parameters: dict[str, int] = Field(default_factory=dict)

    @field_validator("text", "media_file_id")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("blank_value")
        return normalized

    @model_validator(mode="after")
    def validate_contract(self) -> "CampaignContent":
        keys = [cta.key for cta in self.ctas]
        if keys[0] != "primary" or len(keys) != len(set(keys)):
            raise ValueError("primary_cta_required_and_keys_unique")
        if (self.media_type is None) != (self.media_file_id is None):
            raise ValueError("media_type_and_file_id_must_be_set_together")
        if self.segment_type == "inactive":
            if set(self.segment_parameters) != {"inactive_days"}:
                raise ValueError("inactive_days_required")
            if not 1 <= self.segment_parameters["inactive_days"] <= 3650:
                raise ValueError("inactive_days_out_of_range")
        elif self.segment_parameters:
            raise ValueError("segment_parameters_not_allowed")
        return self


class CampaignCreate(CampaignContent):
    campaign_type: CampaignType
    attribution_window_days: int = Field(default=7, ge=1, le=30)
    reason: str | None = Field(default=None, max_length=256)


class CampaignUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=4096)
    media_type: MediaType | None = None
    media_file_id: str | None = Field(default=None, max_length=256)
    clear_media: bool = False
    ctas: list[BroadcastCTA] | None = Field(default=None, min_length=1, max_length=2)
    segment_type: SegmentType | None = None
    segment_parameters: dict[str, int] | None = None
    attribution_window_days: int | None = Field(default=None, ge=1, le=30)
    reason: str | None = Field(default=None, max_length=256)

    @field_validator("text", "media_file_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("blank_value")
        return normalized

    @model_validator(mode="after")
    def validate_update(self) -> "CampaignUpdate":
        if self.clear_media and (self.media_type is not None or self.media_file_id is not None):
            raise ValueError("clear_media_conflicts_with_media")
        if (self.media_type is None) != (self.media_file_id is None):
            raise ValueError("media_type_and_file_id_must_be_set_together")
        if self.ctas is not None:
            keys = [cta.key for cta in self.ctas]
            if keys[0] != "primary" or len(keys) != len(set(keys)):
                raise ValueError("primary_cta_required_and_keys_unique")
        if self.segment_type == "inactive" or (
            self.segment_type is None and self.segment_parameters is not None
        ):
            if self.segment_parameters is not None:
                if set(self.segment_parameters) != {"inactive_days"}:
                    raise ValueError("inactive_days_required")
                if not 1 <= self.segment_parameters["inactive_days"] <= 3650:
                    raise ValueError("inactive_days_out_of_range")
        elif self.segment_parameters:
            raise ValueError("segment_parameters_not_allowed")
        return self


class CampaignAction(BaseModel):
    reason: str | None = Field(default=None, max_length=256)


class CampaignLaunch(CampaignAction):
    expected_content_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
