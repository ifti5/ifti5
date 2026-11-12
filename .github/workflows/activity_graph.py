#!/usr/bin/env python3

"""
Generate an animated SVG contribution activity graph for a GitHub profile.

Output:
    dist/activity-graph.svg

Environment variables:
    GH_TOKEN          GitHub token supplied by GitHub Actions
    PROFILE_USERNAME  GitHub username; defaults to "ifti5"
"""

from __future__ import annotations

import html
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
OUTPUT_FILE = Path("dist/activity-graph.svg")
DAYS_TO_DISPLAY = 90


def fetch_contributions(username: str, token: str) -> dict:
    query = """
    query ProfileContributions($login: String!) {
      user(login: $login) {
        name
        login
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
                weekday
              }
            }
          }
        }
      }
    }
    """

    payload = json.dumps(
        {
            "query": query,
            "variables": {
                "login": username,
            },
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        GRAPHQL_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{username}-profile-activity-generator",
            "Accept": "application/vnd.github+json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub GraphQL request failed with HTTP {error.code}: {details}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Unable to connect to the GitHub GraphQL API: {error}"
        ) from error

    if result.get("errors"):
        messages = "; ".join(
            item.get("message", "Unknown GraphQL error")
            for item in result["errors"]
        )
        raise RuntimeError(f"GitHub GraphQL error: {messages}")

    user = result.get("data", {}).get("user")

    if not user:
        raise RuntimeError(f"GitHub user '{username}' was not found.")

    return user


def collect_days(user_data: dict) -> tuple[list[dict], int]:
    calendar = (
        user_data["contributionsCollection"]["contributionCalendar"]
    )

    days: list[dict] = []

    for week in calendar.get("weeks", []):
        for day in week.get("contributionDays", []):
            days.append(
                {
                    "date": day["date"],
                    "count": int(day["contributionCount"]),
                }
            )

    days.sort(key=lambda item: item["date"])

    return days[-DAYS_TO_DISPLAY:], int(calendar["totalContributions"])


def format_date(date_text: str) -> str:
    return datetime.fromisoformat(date_text).strftime("%b %d")


def make_graph(
    username: str,
    display_name: str,
    days: list[dict],
    yearly_total: int,
) -> str:
    if not days:
        raise RuntimeError("No contribution data was returned by GitHub.")

    width = 1200
    height = 390

    margin_left = 72
    margin_right = 38
    margin_top = 105
    margin_bottom = 62

    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    baseline_y = margin_top + chart_height

    values = [day["count"] for day in days]
    maximum = max(max(values), 1)
    recent_total = sum(values)
    active_days = sum(1 for value in values if value > 0)

    # Use a rounded graph ceiling for cleaner labels.
    graph_ceiling = max(4, int(math.ceil(maximum / 4.0) * 4))

    def point_x(index: int) -> float:
        if len(days) == 1:
            return margin_left + chart_width / 2

        return margin_left + (
            index * chart_width / (len(days) - 1)
        )

    def point_y(value: int) -> float:
        return baseline_y - (value / graph_ceiling) * chart_height

    points = [
        (point_x(index), point_y(day["count"]))
        for index, day in enumerate(days)
    ]

    line_path = " ".join(
        (
            f"M {x:.2f} {y:.2f}"
            if index == 0
            else f"L {x:.2f} {y:.2f}"
        )
        for index, (x, y) in enumerate(points)
    )

    first_x = points[0][0]
    last_x = points[-1][0]

    area_path = (
        f"M {first_x:.2f} {baseline_y:.2f} "
        + " ".join(
            f"L {x:.2f} {y:.2f}" for x, y in points
        )
        + f" L {last_x:.2f} {baseline_y:.2f} Z"
    )

    # Horizontal grid and Y-axis labels.
    grid_elements: list[str] = []

    for level in range(5):
        ratio = level / 4
        y = baseline_y - ratio * chart_height
        label_value = round(graph_ceiling * ratio)

        grid_elements.append(
            f"""
            <line
              class="grid-line"
              x1="{margin_left}"
              y1="{y:.2f}"
              x2="{width - margin_right}"
              y2="{y:.2f}"
            />
            <text
              class="axis-text"
              x="{margin_left - 17}"
              y="{y + 4:.2f}"
              text-anchor="end"
            >{label_value}</text>
            """
        )

    # Date labels.
    label_indices = sorted(
        {
            0,
            len(days) // 4,
            len(days) // 2,
            (len(days) * 3) // 4,
            len(days) - 1,
        }
    )

    date_labels: list[str] = []

    for index in label_indices:
        x = point_x(index)
        label = html.escape(format_date(days[index]["date"]))

        anchor = "middle"

        if index == 0:
            anchor = "start"
        elif index == len(days) - 1:
            anchor = "end"

        date_labels.append(
            f"""
            <text
              class="axis-text"
              x="{x:.2f}"
              y="{baseline_y + 35}"
              text-anchor="{anchor}"
            >{label}</text>
            """
        )

    # Only draw dots for active days to keep the SVG compact.
    dots: list[str] = []

    for index, ((x, y), day) in enumerate(zip(points, days)):
        count = day["count"]

        if count <= 0:
            continue

        radius = min(3.2 + math.log2(count + 1) * 0.65, 6.8)
        delay = (index % 16) * 0.07
        date_label = html.escape(format_date(day["date"]))

        dots.append(
            f"""
            <g>
              <title>{date_label}: {count} contribution{
                  "" if count == 1 else "s"
              }</title>
              <circle
                class="activity-dot"
                cx="{x:.2f}"
                cy="{y:.2f}"
                r="{radius:.2f}"
                style="animation-delay: {delay:.2f}s"
              />
            </g>
            """
        )

    safe_username = html.escape(username)
    safe_display_name = html.escape(display_name or username)

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg
  xmlns="http://www.w3.org/2000/svg"
  width="{width}"
  height="{height}"
  viewBox="0 0 {width} {height}"
  role="img"
  aria-labelledby="graph-title graph-description"
>
  <title id="graph-title">
    {safe_username} animated GitHub contribution activity
  </title>

  <desc id="graph-description">
    Animated graph showing the most recent {len(days)} days of public
    GitHub contribution activity for {safe_display_name}.
  </desc>

  <defs>
    <linearGradient id="background-gradient" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#020617"/>
      <stop offset="42%" stop-color="#0F172A"/>
      <stop offset="72%" stop-color="#1E1B4B"/>
      <stop offset="100%" stop-color="#020617"/>
    </linearGradient>

    <linearGradient id="line-gradient" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#06B6D4"/>
      <stop offset="30%" stop-color="#38BDF8"/>
      <stop offset="58%" stop-color="#8B5CF6"/>
      <stop offset="80%" stop-color="#EC4899"/>
      <stop offset="100%" stop-color="#F59E0B"/>
    </linearGradient>

    <linearGradient id="area-gradient" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#8B5CF6" stop-opacity="0.55"/>
      <stop offset="45%" stop-color="#2563EB" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="#020617" stop-opacity="0"/>
    </linearGradient>

    <radialGradient id="orb-cyan">
      <stop offset="0%" stop-color="#38BDF8" stop-opacity="0.26"/>
      <stop offset="100%" stop-color="#38BDF8" stop-opacity="0"/>
    </radialGradient>

    <radialGradient id="orb-purple">
      <stop offset="0%" stop-color="#A855F7" stop-opacity="0.23"/>
      <stop offset="100%" stop-color="#A855F7" stop-opacity="0"/>
    </radialGradient>

    <filter id="line-glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="4" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>

    <filter id="dot-glow" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>

  <style>
    svg {{
      font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
    }}

    .background {{
      fill: url(#background-gradient);
    }}

    .border {{
      fill: none;
      stroke: #334155;
      stroke-opacity: 0.75;
    }}

    .title {{
      fill: #F8FAFC;
      font-size: 23px;
      font-weight: 700;
      letter-spacing: 0.4px;
    }}

    .subtitle {{
      fill: #94A3B8;
      font-size: 13px;
      font-weight: 500;
    }}

    .metric-value {{
      fill: #F8FAFC;
      font-size: 16px;
      font-weight: 700;
    }}

    .metric-label {{
      fill: #64748B;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1px;
    }}

    .grid-line {{
      stroke: #334155;
      stroke-width: 1;
      stroke-dasharray: 4 8;
      opacity: 0.52;
    }}

    .axis-text {{
      fill: #64748B;
      font-size: 11px;
      font-weight: 500;
    }}

    .area {{
      fill: url(#area-gradient);
      opacity: 0;
      animation: reveal-area 1.1s ease-out 1s forwards;
    }}

    .activity-line {{
      fill: none;
      stroke: url(#line-gradient);
      stroke-width: 4;
      stroke-linecap: round;
      stroke-linejoin: round;
      filter: url(#line-glow);
      path-length: 1;
      stroke-dasharray: 1;
      stroke-dashoffset: 1;
      animation: draw-line 2.8s cubic-bezier(.22,.72,.25,1) forwards;
    }}

    .activity-dot {{
      fill: #F8FAFC;
      stroke: #38BDF8;
      stroke-width: 2;
      filter: url(#dot-glow);
      transform-box: fill-box;
      transform-origin: center;
      animation: pulse-dot 2.5s ease-in-out infinite;
    }}

    .orb-one {{
      animation: float-one 7s ease-in-out infinite alternate;
    }}

    .orb-two {{
      animation: float-two 9s ease-in-out infinite alternate;
    }}

    @keyframes draw-line {{
      from {{
        stroke-dashoffset: 1;
      }}
      to {{
        stroke-dashoffset: 0;
      }}
    }}

    @keyframes reveal-area {{
      from {{
        opacity: 0;
      }}
      to {{
        opacity: 1;
      }}
    }}

    @keyframes pulse-dot {{
      0%, 100% {{
        opacity: 0.72;
        transform: scale(0.88);
      }}
      50% {{
        opacity: 1;
        transform: scale(1.28);
      }}
    }}

    @keyframes float-one {{
      from {{
        transform: translate(-12px, 6px);
      }}
      to {{
        transform: translate(28px, -12px);
      }}
    }}

    @keyframes float-two {{
      from {{
        transform: translate(10px, -4px);
      }}
      to {{
        transform: translate(-24px, 14px);
      }}
    }}

    @media (prefers-reduced-motion: reduce) {{
      .activity-line,
      .area,
      .activity-dot,
      .orb-one,
      .orb-two {{
        animation: none !important;
      }}

      .activity-line {{
        stroke-dashoffset: 0;
      }}

      .area {{
        opacity: 1;
      }}
    }}
  </style>

  <rect
    class="background"
    x="1"
    y="1"
    width="{width - 2}"
    height="{height - 2}"
    rx="24"
  />

  <circle
    class="orb-one"
    cx="210"
    cy="40"
    r="190"
    fill="url(#orb-cyan)"
  />

  <circle
    class="orb-two"
    cx="1050"
    cy="120"
    r="230"
    fill="url(#orb-purple)"
  />

  <rect
    class="border"
    x="1.5"
    y="1.5"
    width="{width - 3}"
    height="{height - 3}"
    rx="23"
  />

  <text class="title" x="38" y="43">
    CONTRIBUTION ACTIVITY
  </text>

  <text class="subtitle" x="38" y="68">
    Latest {len(days)} days for @{safe_username}
  </text>

  <g transform="translate(710 25)">
    <text class="metric-value" x="0" y="16">{recent_total}</text>
    <text class="metric-label" x="0" y="35">RECENT CONTRIBUTIONS</text>
  </g>

  <g transform="translate(900 25)">
    <text class="metric-value" x="0" y="16">{active_days}</text>
    <text class="metric-label" x="0" y="35">ACTIVE DAYS</text>
  </g>

  <g transform="translate(1040 25)">
    <text class="metric-value" x="0" y="16">{yearly_total}</text>
    <text class="metric-label" x="0" y="35">YEAR TOTAL</text>
  </g>

  <g>
    {''.join(grid_elements)}
    {''.join(date_labels)}
  </g>

  <path class="area" d="{area_path}"/>

  <path
    class="activity-line"
    pathLength="1"
    d="{line_path}"
  />

  <g>
    {''.join(dots)}
  </g>
</svg>
"""

    return svg


def main() -> int:
    token = os.environ.get("GH_TOKEN", "").strip()
    username = os.environ.get("PROFILE_USERNAME", "ifti5").strip()

    if not token:
        print(
            "Error: GH_TOKEN is required to query GitHub contribution data.",
            file=sys.stderr,
        )
        return 1

    if not username:
        print(
            "Error: PROFILE_USERNAME cannot be empty.",
            file=sys.stderr,
        )
        return 1

    try:
        print(f"Retrieving contribution data for @{username}...")

        user_data = fetch_contributions(username, token)
        days, yearly_total = collect_days(user_data)

        display_name = user_data.get("name") or user_data.get("login") or username

        svg = make_graph(
            username=username,
            display_name=display_name,
            days=days,
            yearly_total=yearly_total,
        )

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(svg, encoding="utf-8")

        print(f"Generated: {OUTPUT_FILE}")
        print(f"Displayed days: {len(days)}")
        print(f"Yearly contributions: {yearly_total}")

        return 0

    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

