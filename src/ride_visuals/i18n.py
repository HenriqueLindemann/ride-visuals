"""Small, dependency-free localization layer for generated media.

The public package uses English as its source language. Projects can keep a
different default in ``config/config.toml`` without coupling renderers to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any


DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "pt-BR")

_MONTHS_SHORT = {
    "en": ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
    "pt-BR": ("JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"),
}


_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "activity.default": "Activity",
        "collection.title": "Ride collection",
        "collection.parallel.normalized": "All routes · normalized progress",
        "collection.parallel.elapsed": "Mass start · real elapsed time",
        "collection.finish_distribution": "Completed routes",
        "collection.legend.coverage": "{count}/{total} rides with data",
        "collection.legend.coverage_short": "{count}/{total} with data",
        "collection.legend.no_data": "No data",
        "value.unavailable": "—",
        "collection.legend.effort": "Heart-rate zones · bpm",
        "collection.legend.temperature": "Temperature · °C",
        "collection.legend.speed": "Speed · km/h",
        "collection.legend.grade": "Grade · %",
        "collection.legend.altitude": "Altitude · m",
        "metric.activities": "Activities",
        "metric.ascent": "Elevation gain",
        "metric.current_date": "Current date",
        "metric.current_ride": "Current ride",
        "metric.date": "Date",
        "metric.distance": "Distance",
        "metric.distance_progress": "Distance covered",
        "metric.elevation": "Elevation",
        "metric.elevation_profile": "Elevation profile",
        "metric.grade": "Grade",
        "metric.heart_rate": "Heart rate",
        "metric.power": "Power",
        "metric.rides": "Rides",
        "metric.rides_accumulated": "Rides completed",
        "metric.season_distance": "Cumulative distance",
        "metric.month_distance": "Current month",
        "metric.average_ride": "Average ride",
        "metric.longest_so_far": "Longest so far",
        "metric.speed": "Speed",
        "metric.speed_3min": "Speed",
        "metric.temperature": "Temperature",
        "metric.elapsed_time": "Elapsed time",
        "metric.routes_in_motion": "Routes in motion",
        "metric.routes_finished": "Routes finished",
        "metric.combined_distance": "Combined distance",
        "metric.farthest_route": "Farthest route",
        "metric.progress": "Progress",
        "metric.total_distance": "Total distance",
        "map.overview.title": "Ride overview",
        "map.overview.subtitle": "{count} rides · {distance} km · +{ascent} m · {start} — {end}",
        "map.density.title": "Route density",
        "map.density.subtitle": "{count} rides",
        "map.effort.title": "Heart-rate effort",
        "map.effort.subtitle": "{with_data}/{count} rides with heart-rate data",
        "dashboard.title": "Ride summary",
        "dashboard.zones": "Heart-rate zones",
        "dashboard.distance": "Monthly distance · km",
        "dashboard.trimp": "Monthly training load",
        "dashboard.ascent": "Monthly elevation gain · m",
        "dashboard.time": "Moving time · hours",
        "dashboard.records": "Records",
        "dashboard.longest": "Longest ride",
        "dashboard.highest": "Highest elevation gain",
        "dashboard.fastest_sustained": "Fastest avg (> 20 km)",
        "dashboard.peak_hr": "Maximum HR",
        "dashboard.max_speed": "Maximum speed",
        "dashboard.drift": "Average cardiac drift",
        "progress.footer": "Ride Visuals",
        "progress.chapter.1.title": "Summary",
        "progress.chapter.2.title": "Weekly volume",
        "progress.chapter.3.title": "Speed distribution",
        "progress.chapter.4.title": "Heart-rate zones",
        "progress.chapter.5.title": "Training load",
        "progress.chapter.6.title": "Elevation and temperature",
        "progress.chapter.7.title": "Records",
        "progress.chapter.8.title": "Totals",
        "progress.metric.moving_time": "Moving time",
        "progress.metric.hr_coverage": "Rides with heart rate",
        "progress.metric.climbs": "Climbs identified",
        "progress.metric.vam": "Average climbing VAM",
        "progress.metric.total_elevation": "Total elevation gain",
        "progress.metric.average_elevation": "Average per ride",
        "progress.metric.total_distance": "Total distance",
        "progress.metric.total_rides": "Total rides",
        "progress.metric.samples": "Telemetry points",
        "progress.metric.speed_samples": "Speed samples",
        "progress.metric.hr_samples": "Heart-rate samples",
        "progress.metric.temp_samples": "Temperature samples",
        "progress.metric.weekly_distance": "Weekly distance · km · orange line = 4-week average",
        "progress.metric.weekly_rides": "Rides per week",
        "progress.metric.speed_distribution": "Speed samples · km/h",
        "progress.metric.median_speed": "Median speed",
        "progress.metric.p90_speed": "90th percentile speed",
        "progress.metric.p99_speed": "99th percentile speed",
        "progress.metric.peak_speed": "Peak speed",
        "progress.metric.median_hr": "Median HR",
        "progress.metric.p90_hr": "HR · 90th percentile",
        "progress.metric.peak_hr": "Maximum HR",
        "progress.metric.temperature_band": "Temperature range",
        "progress.metric.hardest_effort": "Highest relative effort",
        "progress.metric.fastest_sustained": "Fastest average · rides over 20 km",
        "timeline.title": "Ride telemetry",
        "timeline.cumulative_distance": "Cumulative distance · km",
        "timeline.ride_distance": "Ride distance · km",
        "timeline.elevation_gain": "Elevation gain · m",
        "timeline.average_speed": "Average speed · km/h",
        "timeline.average_hr": "Average heart rate · bpm",
        "timeline.temperature": "Average temperature · °C",
        "timeline.waiting_first_ride": "Waiting for the first ride",
        "timeline.ride_number": "Ride {number}",
        "unit.activities": "activities",
        "unit.rides": "rides",
        "video.season_summary": "{distance} km · {ascent} m · {count} activities",
        "video.season_title": "{count} rides",
    },
    "pt-BR": {
        "activity.default": "Atividade",
        "collection.title": "Coleção de pedaladas",
        "collection.parallel.normalized": "Todas as rotas · progresso normalizado",
        "collection.parallel.elapsed": "Largada conjunta · tempo real decorrido",
        "collection.finish_distribution": "Rotas concluídas",
        "collection.legend.coverage": "{count}/{total} pedaladas com dados",
        "collection.legend.coverage_short": "{count}/{total} com dados",
        "collection.legend.no_data": "Sem dados",
        "value.unavailable": "—",
        "collection.legend.effort": "Zonas cardíacas · bpm",
        "collection.legend.temperature": "Temperatura · °C",
        "collection.legend.speed": "Velocidade · km/h",
        "collection.legend.grade": "Inclinação · %",
        "collection.legend.altitude": "Altitude · m",
        "metric.activities": "Atividades",
        "metric.ascent": "Ganho de elevação",
        "metric.current_date": "Data atual",
        "metric.current_ride": "Pedalada atual",
        "metric.date": "Data",
        "metric.distance": "Distância",
        "metric.distance_progress": "Distância percorrida",
        "metric.elevation": "Elevação",
        "metric.elevation_profile": "Perfil de elevação",
        "metric.grade": "Inclinação",
        "metric.heart_rate": "Frequência cardíaca",
        "metric.power": "Potência",
        "metric.rides": "Pedaladas",
        "metric.rides_accumulated": "Pedaladas concluídas",
        "metric.season_distance": "Distância acumulada",
        "metric.month_distance": "Mês atual",
        "metric.average_ride": "Média por pedalada",
        "metric.longest_so_far": "Maior até agora",
        "metric.speed": "Velocidade",
        "metric.speed_3min": "Velocidade",
        "metric.temperature": "Temperatura",
        "metric.elapsed_time": "Tempo decorrido",
        "metric.routes_in_motion": "Rotas em movimento",
        "metric.routes_finished": "Rotas concluídas",
        "metric.combined_distance": "Distância combinada",
        "metric.farthest_route": "Rota mais distante",
        "metric.progress": "Progresso",
        "metric.total_distance": "Distância total",
        "map.overview.title": "Visão geral das pedaladas",
        "map.overview.subtitle": "{count} pedaladas · {distance} km · +{ascent} m · {start} — {end}",
        "map.density.title": "Densidade de rotas",
        "map.density.subtitle": "{count} pedaladas",
        "map.effort.title": "Esforço cardíaco",
        "map.effort.subtitle": "{with_data}/{count} pedaladas com frequência cardíaca",
        "dashboard.title": "Resumo das pedaladas",
        "dashboard.zones": "Zonas de frequência cardíaca",
        "dashboard.distance": "Distância mensal · km",
        "dashboard.trimp": "Carga mensal de treino",
        "dashboard.ascent": "Ganho de elevação mensal · m",
        "dashboard.time": "Tempo em movimento · horas",
        "dashboard.records": "Recordes",
        "dashboard.longest": "Maior pedalada",
        "dashboard.highest": "Maior ganho de elevação",
        "dashboard.fastest_sustained": "Maior média (> 20 km)",
        "dashboard.peak_hr": "FC máxima",
        "dashboard.max_speed": "Velocidade máxima",
        "dashboard.drift": "Desacoplamento cardíaco médio",
        "progress.footer": "Ride Visuals",
        "progress.chapter.1.title": "Resumo",
        "progress.chapter.2.title": "Volume semanal",
        "progress.chapter.3.title": "Distribuição de velocidade",
        "progress.chapter.4.title": "Zonas de frequência cardíaca",
        "progress.chapter.5.title": "Carga de treino",
        "progress.chapter.6.title": "Elevação e temperatura",
        "progress.chapter.7.title": "Recordes",
        "progress.chapter.8.title": "Totais",
        "progress.metric.moving_time": "Tempo em movimento",
        "progress.metric.hr_coverage": "Pedaladas com frequência cardíaca",
        "progress.metric.climbs": "Subidas identificadas",
        "progress.metric.vam": "VAM médio em subida",
        "progress.metric.total_elevation": "Ganho total de elevação",
        "progress.metric.average_elevation": "Média por pedalada",
        "progress.metric.total_distance": "Distância total",
        "progress.metric.total_rides": "Total de pedaladas",
        "progress.metric.samples": "Pontos de telemetria",
        "progress.metric.speed_samples": "Amostras de velocidade",
        "progress.metric.hr_samples": "Amostras de frequência cardíaca",
        "progress.metric.temp_samples": "Amostras de temperatura",
        "progress.metric.weekly_distance": "Distância semanal · km · linha laranja = média de 4 semanas",
        "progress.metric.weekly_rides": "Pedaladas por semana",
        "progress.metric.speed_distribution": "Amostras de velocidade · km/h",
        "progress.metric.median_speed": "Velocidade mediana",
        "progress.metric.p90_speed": "Percentil 90 de velocidade",
        "progress.metric.p99_speed": "Percentil 99 de velocidade",
        "progress.metric.peak_speed": "Velocidade de pico",
        "progress.metric.median_hr": "FC mediana",
        "progress.metric.p90_hr": "FC · percentil 90",
        "progress.metric.peak_hr": "FC máxima",
        "progress.metric.temperature_band": "Faixa de temperatura",
        "progress.metric.hardest_effort": "Maior esforço relativo",
        "progress.metric.fastest_sustained": "Maior média · pedaladas acima de 20 km",
        "timeline.title": "Telemetria das pedaladas",
        "timeline.cumulative_distance": "Distância acumulada · km",
        "timeline.ride_distance": "Distância por pedalada · km",
        "timeline.elevation_gain": "Ganho de elevação · m",
        "timeline.average_speed": "Velocidade média · km/h",
        "timeline.average_hr": "Frequência cardíaca média · bpm",
        "timeline.temperature": "Temperatura média · °C",
        "timeline.waiting_first_ride": "Aguardando a primeira pedalada",
        "timeline.ride_number": "Pedalada {number}",
        "unit.activities": "atividades",
        "unit.rides": "pedaladas",
        "video.season_summary": "{distance} km · {ascent} m · {count} atividades",
        "video.season_title": "{count} pedaladas",
    },
}


def sanitize_display_text(value: Any) -> str:
    """Replace emoji glyphs that are not available in deterministic render fonts."""
    normalized = str(value).replace("->", "→")
    normalized = "".join(" · " if ord(character) > 0xFFFF else character for character in normalized)
    normalized = re.sub(r"\s*·(?:\s*·)*\s*", " · ", normalized)
    return re.sub(r"\s+", " ", normalized).strip(" ·")


def normalize_locale(locale: str | None) -> str:
    """Return a supported locale, accepting common POSIX/BCP-47 variants."""
    if not locale:
        return DEFAULT_LOCALE
    normalized = locale.replace("_", "-").strip()
    lower = normalized.lower()
    if lower.startswith("pt"):
        return "pt-BR"
    if lower.startswith("en"):
        return "en"
    raise ValueError(
        f"Unsupported locale {locale!r}. Choose one of: {', '.join(SUPPORTED_LOCALES)}"
    )


@dataclass(frozen=True)
class Translator:
    """Translate copy and format values consistently inside visual outputs."""

    locale: str = DEFAULT_LOCALE

    def __post_init__(self) -> None:
        object.__setattr__(self, "locale", normalize_locale(self.locale))

    def text(self, key: str, **values: Any) -> str:
        source = _MESSAGES[DEFAULT_LOCALE]
        catalog = _MESSAGES[self.locale]
        template = catalog.get(key, source.get(key))
        if template is None:
            raise KeyError(f"Unknown translation key: {key}")
        return template.format(**values)

    def number(
        self,
        value: float | int,
        decimals: int = 0,
        *,
        grouping: bool = True,
    ) -> str:
        """Format a number without changing its stored unit or precision."""
        spec = f",.{decimals}f" if grouping else f".{decimals}f"
        rendered = format(value, spec)
        if self.locale == "pt-BR":
            rendered = rendered.replace(",", "__group__").replace(".", ",").replace("__group__", ".")
        return rendered

    def date(self, value: date | datetime) -> str:
        if self.locale == "pt-BR":
            return value.strftime("%d/%m/%Y")
        return value.strftime("%b %d, %Y")

    def month_short(self, value: date | datetime) -> str:
        """Return a stable, uppercase short month label for chart axes."""
        return _MONTHS_SHORT[self.locale][value.month - 1]
