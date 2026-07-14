from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

user_projects = Table(
    "user_projects",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    projects: Mapped[List["Project"]] = relationship(secondary=user_projects, order_by="Project.name")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    environments: Mapped[List["Environment"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(Environment.is_primary), Environment.name",
    )

    @property
    def primary_environment(self) -> Optional["Environment"]:
        for environment in self.environments:
            if environment.is_primary:
                return environment
        return self.environments[0] if self.environments else None


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    drupal_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_response_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_check_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    ssl_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ssl_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ssl_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ssl_days_remaining: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ssl_issuer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ssl_subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ssl_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    last_seo_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seo_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_seo_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_seo_issue_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_seo_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    last_lighthouse_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_lighthouse_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_lighthouse_performance: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_lighthouse_accessibility: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_lighthouse_best_practices: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_lighthouse_seo: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_lighthouse_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    cache_warm_sitemap_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cache_warm_axes_yaml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_cache_warm_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_cache_warm_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_cache_warm_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_cache_warm_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_cache_warm_success: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_cache_warm_failed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_cache_warm_hit_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    price_audit_listing_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price_audit_link_pattern: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price_audit_upfront_selector: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price_audit_financing_selector: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price_audit_price_selector: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price_audit_color_selector: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price_audit_capacity_selector: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_price_audit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_price_audit_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_price_audit_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_price_audit_matched: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_price_audit_mismatched: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="environments")
    health_checks: Mapped[List["HealthCheck"]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        order_by="desc(HealthCheck.checked_at)",
    )
    seo_checks: Mapped[List["SeoCheck"]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        order_by="desc(SeoCheck.checked_at)",
    )
    lighthouse_checks: Mapped[List["LighthouseCheck"]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        order_by="desc(LighthouseCheck.checked_at)",
    )
    cache_warm_checks: Mapped[List["CacheWarmCheck"]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        order_by="desc(CacheWarmCheck.checked_at)",
    )
    price_audits: Mapped[List["PriceAudit"]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        order_by="desc(PriceAudit.created_at)",
    )
    cron_jobs: Mapped[List["CronJob"]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        order_by="CronJob.check_type",
    )
    scenarios: Mapped[List["Scenario"]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        order_by="Scenario.created_at",
    )


class HealthCheck(Base):
    __tablename__ = "health_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    response_headers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    environment: Mapped["Environment"] = relationship(back_populates="health_checks")


class SeoCheck(Base):
    __tablename__ = "seo_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    load_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    meta_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    meta_robots: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    h1_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    h1_text: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    image_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    images_missing_alt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    internal_link_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    external_link_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    has_viewport: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    lang: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    og_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    og_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    og_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    has_structured_data: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    issues: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    environment: Mapped["Environment"] = relationship(back_populates="seo_checks")


class LighthouseCheck(Base):
    __tablename__ = "lighthouse_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    performance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    accessibility_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    best_practices_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    seo_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    audits: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    environment: Mapped["Environment"] = relationship(back_populates="lighthouse_checks")


class CacheWarmCheck(Base):
    __tablename__ = "cache_warm_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    url_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_jobs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    failed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cache_hits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cache_misses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cache_bypass: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unknown_cache_state: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hit_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    environment: Mapped["Environment"] = relationship(back_populates="cache_warm_checks")


class PriceAudit(Base):
    __tablename__ = "price_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    excel_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    total_products: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_products: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_product_label: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    product_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    excel_row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    matched_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mismatched_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    only_in_site_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    only_in_excel_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    results_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    environment: Mapped["Environment"] = relationship(back_populates="price_audits")


class CronJob(Base):
    __tablename__ = "cron_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    check_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scenario_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=True
    )
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_run_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notify_emails: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    environment: Mapped["Environment"] = relationship(back_populates="cron_jobs")
    scenario: Mapped[Optional["Scenario"]] = relationship()


class EnvironmentComparison(Base):
    __tablename__ = "environment_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    environment_a_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    environment_b_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped["Project"] = relationship()
    environment_a: Mapped["Environment"] = relationship(foreign_keys=[environment_a_id])
    environment_b: Mapped["Environment"] = relationship(foreign_keys=[environment_b_id])
    pages: Mapped[List["ComparisonPage"]] = relationship(
        back_populates="comparison",
        cascade="all, delete-orphan",
        order_by="ComparisonPage.id",
    )


class ComparisonPage(Base):
    __tablename__ = "comparison_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(
        ForeignKey("environment_comparisons.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    screenshot_a_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    screenshot_b_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    diff_image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    diff_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_differences: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    comparison: Mapped["EnvironmentComparison"] = relationship(back_populates="pages")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    environment: Mapped["Environment"] = relationship(back_populates="scenarios")
    steps: Mapped[List["ScenarioStep"]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        order_by="ScenarioStep.position, ScenarioStep.id",
    )
    runs: Mapped[List["ScenarioRun"]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        order_by="desc(ScenarioRun.run_at)",
    )

    @property
    def last_run(self) -> Optional["ScenarioRun"]:
        return self.runs[0] if self.runs else None


class ScenarioStep(Base):
    __tablename__ = "scenario_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_type: Mapped[str] = mapped_column(String(30), nullable=False)

    path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    selector: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    value: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    value2: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wait_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    scenario: Mapped["Scenario"] = relationship(back_populates="steps")


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    scenario: Mapped["Scenario"] = relationship(back_populates="runs")
    step_results: Mapped[List["ScenarioStepResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ScenarioStepResult.position",
    )


class ScenarioStepResult(Base):
    __tablename__ = "scenario_step_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_runs.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    run: Mapped["ScenarioRun"] = relationship(back_populates="step_results")
