"""Unified data models. Fields a platform lacks are left as None, never guessed."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Metrics(BaseModel):
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    collects: int | None = None
    views: int | None = None


class UserMetrics(BaseModel):
    followers: int | None = None
    following: int | None = None
    posts: int | None = None


class MediaItem(BaseModel):
    type: Literal["video", "image", "audio"]
    url: str
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    size: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    encrypted: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class SocialUser(BaseModel):
    id: str
    platform: str
    name: str | None = None
    avatar_url: str | None = None
    url: str | None = None
    bio: str | None = None
    metrics: UserMetrics = Field(default_factory=UserMetrics)
    raw: Any = None


class SocialPost(BaseModel):
    id: str
    platform: str
    type: Literal["video", "image", "article", "text"] | None = None
    title: str | None = None
    content: str | None = None
    author: SocialUser | None = None
    url: str | None = None
    cover_url: str | None = None
    media: list[MediaItem] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)
    publish_time: str | None = None
    tags: list[str] = Field(default_factory=list)
    raw: Any = None


class SocialComment(BaseModel):
    id: str
    platform: str
    post_id: str
    parent_id: str | None = None
    author: SocialUser | None = None
    content: str | None = None
    likes: int | None = None
    publish_time: str | None = None
    raw: Any = None


class SearchResult(BaseModel):
    platform: str
    keyword: str
    cursor: str | None = None
    items: list[SocialPost | SocialUser] = Field(default_factory=list)
