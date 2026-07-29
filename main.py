import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Path as FastAPIPath, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from redis.exceptions import RedisError

WEBHOOK_PATH_RE = re.compile(r"^/api/webhooks/(\d+)/([A-Za-z0-9_-]+)$")
FAVICON_PATH = Path(__file__).with_name("favicon.png")
FORWARDED_UPSTREAM_HEADERS = frozenset(
    {
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-ratelimit-reset-after",
        "x-ratelimit-bucket",
        "x-ratelimit-global",
        "x-ratelimit-scope",
    }
)
INDEX_HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Discord Webhook Proxy</title>
    <meta name="description" content="A Friendly, Queue-Safe Relay For Discord Webhooks.">
    <meta property="og:title" content="Discord Webhook Proxy">
    <meta property="og:description" content="A Friendly, Queue-Safe Relay For Discord Webhooks.">
    <meta property="og:type" content="website">
    <meta property="og:image" content="/og-image.png">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="theme-color" content="#6D73FF">
    <link rel="icon" type="image/png" href="/favicon.png">
    <style nonce="__NONCE__">
        :root {
            color-scheme: dark;
            --bg: #0b0d15;
            --bg-soft: #111522;
            --card: rgba(24, 28, 43, 0.78);
            --card-strong: rgba(31, 36, 55, 0.92);
            --card-soft: rgba(255, 255, 255, 0.055);
            --border: rgba(255, 255, 255, 0.12);
            --border-strong: rgba(255, 255, 255, 0.18);
            --text: #f6f7fb;
            --muted: #a9b0c3;
            --soft: #d7dcf0;
            --accent: #6d73ff;
            --accent-2: #ff8d8f;
            --green: #68f2a3;
            --yellow: #ffd166;
            --red: #ff6b6b;
            --shadow: 0 30px 90px rgba(0, 0, 0, 0.42);
            --radius-xl: 30px;
            --radius-lg: 22px;
            --radius-md: 16px;
            --mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
        }

        * {
            box-sizing: border-box;
        }

        html {
            scroll-behavior: smooth;
        }

        body {
            margin: 0;
            min-height: 100vh;
            background:
                radial-gradient(circle at 16% 10%, rgba(109, 115, 255, 0.34), transparent 30rem),
                radial-gradient(circle at 84% 8%, rgba(255, 141, 143, 0.22), transparent 28rem),
                radial-gradient(circle at 50% 95%, rgba(104, 242, 163, 0.12), transparent 36rem),
                linear-gradient(180deg, #080a12 0%, var(--bg) 46%, #10131f 100%);
            color: var(--text);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            overflow-x: hidden;
        }

        body::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background:
                linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
            background-size: 42px 42px;
            mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.82), transparent 78%);
        }

        a {
            color: inherit;
            text-decoration: none;
        }

        button,
        input {
            font: inherit;
        }

        .page {
            width: min(1180px, calc(100% - 36px));
            margin: 0 auto;
            padding: 28px 0 44px;
            position: relative;
            z-index: 1;
        }

        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 20px;
            margin-bottom: 48px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
            min-width: 0;
        }

        .brand-logo {
            width: 48px;
            height: 48px;
            border-radius: 17px;
            background: rgba(109, 115, 255, 0.14);
            border: 1px solid rgba(109, 115, 255, 0.26);
            box-shadow: 0 0 34px rgba(109, 115, 255, 0.24);
            padding: 7px;
        }

        .brand-text {
            display: grid;
            gap: 3px;
        }

        .brand-text strong {
            color: #fff;
            font-size: 15px;
            letter-spacing: 0.01em;
        }

        .brand-text span {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.35;
        }

        .nav-actions {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 10px;
            flex-wrap: wrap;
        }

        .pill-link {
            display: inline-flex;
            align-items: center;
            gap: 9px;
            min-height: 42px;
            padding: 0 15px;
            border-radius: 999px;
            border: 1px solid var(--border);
            background: rgba(24, 28, 43, 0.62);
            color: var(--soft);
            font-size: 13px;
            font-weight: 800;
            transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease;
        }

        .pill-link:hover {
            transform: translateY(-1px);
            border-color: rgba(109, 115, 255, 0.48);
            background: rgba(31, 36, 55, 0.92);
        }

        .github-mark {
            width: 20px;
            height: 20px;
            display: inline-grid;
            place-items: center;
        }

        .github-mark svg {
            width: 20px;
            height: 20px;
        }

        .hero {
            display: grid;
            grid-template-columns: minmax(0, 0.95fr) minmax(360px, 1.05fr);
            gap: 34px;
            align-items: center;
        }

        .hero-copy {
            padding: 18px 0;
        }

        .eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 9px;
            margin-bottom: 20px;
            padding: 9px 13px;
            border-radius: 999px;
            border: 1px solid rgba(104, 242, 163, 0.22);
            background: rgba(104, 242, 163, 0.09);
            color: var(--green);
            font-size: 12px;
            font-weight: 900;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: var(--green);
            box-shadow: 0 0 18px rgba(104, 242, 163, 0.72);
            animation: pulse 1.9s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% {
                opacity: 1;
                transform: scale(1);
            }

            50% {
                opacity: 0.55;
                transform: scale(0.76);
            }
        }

        h1,
        h2,
        h3,
        p {
            margin-top: 0;
        }

        h1 {
            max-width: 780px;
            margin-bottom: 20px;
            color: #fff;
            font-size: clamp(42px, 6.4vw, 76px);
            line-height: 0.96;
            letter-spacing: -0.058em;
        }

        .gradient-text {
            background: linear-gradient(92deg, #ffffff 0%, #e7e9ff 34%, #9fa5ff 64%, #ffabad 100%);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }

        .hero-copy p {
            max-width: 640px;
            margin-bottom: 24px;
            color: var(--soft);
            font-size: 16px;
            line-height: 1.78;
        }

        .hero-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .mini-badge {
            display: inline-flex;
            align-items: center;
            min-height: 34px;
            padding: 0 12px;
            border-radius: 999px;
            border: 1px solid var(--border);
            background: rgba(255, 255, 255, 0.052);
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
        }

        .panel {
            overflow: hidden;
            border-radius: var(--radius-xl);
            border: 1px solid var(--border);
            background: linear-gradient(180deg, rgba(31, 36, 55, 0.94), rgba(18, 22, 35, 0.9));
            box-shadow: var(--shadow);
            backdrop-filter: blur(20px);
        }

        .panel-bar {
            min-height: 54px;
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            gap: 14px;
            padding: 0 20px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            background: rgba(8, 10, 18, 0.46);
        }

        .lights {
            display: flex;
            gap: 8px;
        }

        .light {
            width: 12px;
            height: 12px;
            border-radius: 999px;
        }

        .light.red {
            background: var(--red);
        }

        .light.yellow {
            background: var(--yellow);
        }

        .light.green {
            background: var(--green);
        }

        .panel-title {
            color: var(--muted);
            font-family: var(--mono);
            font-size: 12px;
            letter-spacing: 0.08em;
            white-space: nowrap;
        }

        .compiler {
            padding: clamp(22px, 4vw, 34px);
        }

        .compiler-header {
            margin-bottom: 26px;
        }

        .compiler h2 {
            margin-bottom: 9px;
            color: #fff;
            font-size: clamp(24px, 3vw, 32px);
            letter-spacing: -0.035em;
        }

        .compiler-subtitle {
            max-width: 580px;
            margin-bottom: 0;
            color: var(--muted);
            font-size: 14px;
            line-height: 1.68;
        }

        .form-stack {
            display: grid;
            gap: 22px;
        }

        .field {
            display: grid;
            gap: 11px;
        }

        .field label {
            color: var(--soft);
            font-size: 12px;
            font-weight: 900;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        .input-wrap {
            position: relative;
        }

        .prompt {
            position: absolute;
            left: 15px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--accent);
            font-family: var(--mono);
            font-weight: 900;
            pointer-events: none;
        }

        input {
            width: 100%;
            min-height: 58px;
            border-radius: 18px;
            border: 1px solid rgba(255, 255, 255, 0.105);
            background: rgba(8, 10, 18, 0.74);
            color: var(--green);
            outline: none;
            padding: 16px 18px 16px 38px;
            font-family: var(--mono);
            font-size: 13px;
            line-height: 1.4;
            transition: border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
        }

        input::placeholder {
            color: #697085;
        }

        input:focus {
            border-color: rgba(109, 115, 255, 0.9);
            background: rgba(8, 10, 18, 0.92);
            box-shadow: 0 0 0 4px rgba(109, 115, 255, 0.16);
        }

        .output-input {
            padding-right: 112px;
        }

        .button {
            width: 100%;
            min-height: 58px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            border: 0;
            border-radius: 18px;
            background: linear-gradient(135deg, var(--accent), #5259df);
            color: #fff;
            box-shadow: 0 18px 34px rgba(109, 115, 255, 0.3);
            cursor: pointer;
            font-size: 15px;
            font-weight: 950;
            transition: transform 0.18s ease, filter 0.18s ease;
        }

        .button:hover {
            transform: translateY(-1px);
            filter: brightness(1.08);
        }

        .copy-button {
            position: absolute;
            top: 7px;
            right: 7px;
            bottom: 7px;
            width: 92px;
            border: 1px solid rgba(255, 255, 255, 0.11);
            border-radius: 13px;
            background: rgba(255, 255, 255, 0.092);
            color: #fff;
            cursor: pointer;
            font-size: 14px;
            font-weight: 950;
            transition: background 0.18s ease, transform 0.18s ease;
        }

        .copy-button:hover {
            background: rgba(255, 255, 255, 0.14);
            transform: translateY(-1px);
        }

        .error {
            display: none;
            color: #ffabad;
            font-size: 12px;
            font-weight: 850;
            line-height: 1.45;
        }

        .error.visible {
            display: block;
        }

        .helper {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.58;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 14px;
            margin-top: 28px;
        }

        .stat-card {
            min-height: 112px;
            display: grid;
            align-content: center;
            gap: 7px;
            padding: 18px;
            border-radius: 20px;
            border: 1px solid rgba(255, 255, 255, 0.09);
            background: rgba(255, 255, 255, 0.055);
        }

        .stat-card strong {
            color: #fff;
            font-size: clamp(26px, 3vw, 34px);
            line-height: 1;
            letter-spacing: -0.045em;
        }

        .stat-card span {
            color: var(--muted);
            font-size: 12px;
            font-weight: 850;
            line-height: 1.38;
        }

        .section {
            margin-top: 34px;
            padding: clamp(22px, 3.4vw, 34px);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            background: rgba(24, 28, 43, 0.58);
            box-shadow: 0 18px 62px rgba(0, 0, 0, 0.22);
            backdrop-filter: blur(14px);
        }

        .section-header {
            max-width: 760px;
            margin-bottom: 24px;
        }

        .section h2 {
            margin-bottom: 10px;
            color: #fff;
            font-size: clamp(25px, 3.2vw, 38px);
            line-height: 1.06;
            letter-spacing: -0.045em;
        }

        .section-header p {
            margin-bottom: 0;
            color: var(--muted);
            font-size: 15px;
            line-height: 1.7;
        }

        .cards,
        .privacy-grid,
        .rules-grid {
            display: grid;
            gap: 14px;
        }

        .cards {
            grid-template-columns: repeat(4, 1fr);
        }

        .privacy-grid,
        .rules-grid {
            grid-template-columns: repeat(3, 1fr);
        }

        .info-card,
        .privacy-card,
        .rule-card {
            min-height: 150px;
            padding: 19px;
            border: 1px solid rgba(255, 255, 255, 0.09);
            border-radius: 22px;
            background: rgba(255, 255, 255, 0.052);
        }

        .icon {
            width: 38px;
            height: 38px;
            display: grid;
            place-items: center;
            margin-bottom: 16px;
            border-radius: 14px;
            background: rgba(109, 115, 255, 0.14);
            color: #dfe1ff;
            font-size: 18px;
        }

        .info-card h3,
        .privacy-card h3,
        .rule-card h3 {
            margin-bottom: 8px;
            color: #fff;
            font-size: 15px;
            line-height: 1.25;
        }

        .info-card p,
        .privacy-card p,
        .rule-card p {
            margin-bottom: 0;
            color: var(--muted);
            font-size: 13px;
            line-height: 1.62;
        }

        .footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
            margin-top: 30px;
            padding: 22px 2px 4px;
            color: var(--muted);
            font-size: 13px;
        }

        .footer strong {
            color: #fff;
        }

        .online {
            color: var(--green);
        }

        .credit {
            display: inline-flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        @media (max-width: 980px) {
            .hero {
                grid-template-columns: 1fr;
            }

            .cards {
                grid-template-columns: repeat(2, 1fr);
            }

            .privacy-grid,
            .rules-grid {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 700px) {
            .page {
                width: min(100% - 22px, 1180px);
                padding-top: 18px;
            }

            .nav {
                align-items: flex-start;
                flex-direction: column;
                margin-bottom: 34px;
            }

            .nav-actions {
                justify-content: flex-start;
            }

            .brand-logo {
                width: 44px;
                height: 44px;
            }

            .panel-bar {
                grid-template-columns: 1fr;
                justify-items: start;
                padding: 14px 18px;
            }

            .panel-bar > span:last-child {
                display: none;
            }

            .compiler {
                padding: 20px;
            }

            .form-stack {
                gap: 20px;
            }

            input {
                min-height: 56px;
                font-size: 12px;
            }

            .output-input {
                padding-right: 92px;
            }

            .copy-button {
                width: 76px;
                font-size: 13px;
            }

            .stats-grid,
            .cards {
                grid-template-columns: 1fr;
            }

            .footer {
                align-items: flex-start;
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <main class="page">
        <nav class="nav" aria-label="Primary">
            <a class="brand" href="/" aria-label="Discord Webhook Proxy Home">
                <img class="brand-logo" src="/favicon.png" alt="">
                <span class="brand-text">
                    <strong>Discord Webhook Proxy</strong>
                    <span>A calmer path for busy webhook traffic</span>
                </span>
            </a>
            <div class="nav-actions">
                <a class="pill-link" href="https://devforum.roblox.com/t/release-discord-webhook-proxy-your-webhooks-turbocharged/4647835/1" target="_blank" rel="noopener noreferrer">DevForum Release</a>
                <a class="pill-link" href="https://github.com/dqlistic/Discord-Webhook-Proxy" target="_blank" rel="noopener noreferrer" aria-label="GitHub Repository">
                    <span class="github-mark" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                            <path d="M12 2.25c-5.52 0-10 4.48-10 10 0 4.42 2.86 8.16 6.84 9.49.5.09.68-.22.68-.48 0-.23-.01-.86-.01-1.69-2.78.6-3.37-1.19-3.37-1.19-.45-1.15-1.11-1.46-1.11-1.46-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.08.63-1.33-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.64 0 0 .84-.27 2.75 1.02A9.52 9.52 0 0 1 12 7.22c.85 0 1.7.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.37.2 2.39.1 2.64.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.86 0 1.34-.01 2.42-.01 2.75 0 .27.18.58.69.48A10.01 10.01 0 0 0 22 12.25c0-5.52-4.48-10-10-10Z"/>
                        </svg>
                    </span>
                    GitHub
                </a>
            </div>
        </nav>

        <section class="hero">
            <div class="hero-copy">
                <span class="eyebrow"><span class="status-dot"></span> Service Online</span>
                <h1><span class="gradient-text">A Friendly Relay For Busy Discord Webhooks.</span></h1>
                <p>Paste your Discord webhook, create a proxy endpoint, and let the service smooth out busy moments with a safe queue, respectful retries, and replica-aware delivery.</p>
                <div class="hero-badges">
                    <span class="mini-badge">Queue-Safe Delivery</span>
                    <span class="mini-badge">Discord Rate-Limit Friendly</span>
                    <span class="mini-badge">Replica-Ready Workers</span>
                    <span class="mini-badge">Simple Drop-In URL</span>
                </div>
            </div>

            <section class="panel" aria-label="Webhook Proxy Converter">
                <div class="panel-bar">
                    <div class="lights" aria-hidden="true">
                        <span class="light red"></span>
                        <span class="light yellow"></span>
                        <span class="light green"></span>
                    </div>
                    <span class="panel-title">proxy.converter</span>
                    <span></span>
                </div>

                <div class="compiler">
                    <div class="compiler-header">
                        <h2>Create Your Proxy Endpoint</h2>
                        <p class="compiler-subtitle">Your webhook token stays inside the generated URL, so treat the proxy endpoint like the original webhook and only share it with trusted systems.</p>
                    </div>

                    <div class="form-stack">
                        <div class="field">
                            <label for="webhook-input">Original Discord Webhook URL</label>
                            <div class="input-wrap">
                                <span class="prompt">&gt;</span>
                                <input id="webhook-input" type="text" placeholder="https://discord.com/api/webhooks/..." autocomplete="off" spellcheck="false" inputmode="url">
                            </div>
                            <span id="error-msg" class="error">Please enter a Discord webhook URL that starts with /api/webhooks/.</span>
                        </div>

                        <button id="compile-btn" class="button" type="button">Create Proxy Endpoint</button>

                        <div class="field">
                            <label for="webhook-output">Proxy Endpoint</label>
                            <div class="input-wrap">
                                <span class="prompt">~</span>
                                <input id="webhook-output" class="output-input" type="text" readonly placeholder="Your proxy endpoint will appear here.">
                                <button id="copy-btn" class="copy-button" type="button">Copy</button>
                            </div>
                            <span class="helper">Use this proxy URL anywhere you would normally use the original Discord webhook URL.</span>
                        </div>
                    </div>

                    <div class="stats-grid" aria-label="Service Counters">
                        <div class="stat-card">
                            <strong id="unique-webhooks">0</strong>
                            <span>Unique Webhooks Protected</span>
                        </div>
                        <div class="stat-card">
                            <strong id="requests-served">0</strong>
                            <span>Requests Accepted By The Proxy</span>
                        </div>
                        <div class="stat-card">
                            <strong id="sent-count">0</strong>
                            <span>Messages Sent To Discord</span>
                        </div>
                    </div>
                </div>
            </section>
        </section>

        <section class="section" id="information">
            <div class="section-header">
                <h2>Made To Keep Busy Moments Smooth.</h2>
                <p>The proxy accepts webhook requests quickly, queues them safely, and sends them to Discord at a respectful pace so short bursts do not turn into failed deliveries.</p>
            </div>
            <div class="cards">
                <article class="info-card">
                    <div class="icon">🌊</div>
                    <h3>Smooths Out Bursts</h3>
                    <p>Sudden traffic is placed into Redis-backed queues instead of being dropped immediately.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🧭</div>
                    <h3>Keeps Webhooks Ordered</h3>
                    <p>Each webhook has its own first-in, first-out queue for predictable delivery.</p>
                </article>
                <article class="info-card">
                    <div class="icon">⏳</div>
                    <h3>Waits When Discord Asks</h3>
                    <p>Discord retry headers are respected so the service slows down when needed.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🛟</div>
                    <h3>Recovers Lost Work</h3>
                    <p>If a replica stops mid-dispatch, another worker can reclaim the job safely.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🧱</div>
                    <h3>Blocks Abusive Loops</h3>
                    <p>Repeated over-limit requests can be paused temporarily before they hurt the service.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🧪</div>
                    <h3>Checks Payloads Early</h3>
                    <p>Empty, oversized, malformed, and conflicting requests are rejected before dispatch.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🌍</div>
                    <h3>Works Across Regions</h3>
                    <p>Replicas coordinate through Redis so multiple regions can share one delivery pipeline.</p>
                </article>
                <article class="info-card">
                    <div class="icon">📈</div>
                    <h3>Shows Helpful Counters</h3>
                    <p>Simple live counters help users see that the proxy is active and processing work.</p>
                </article>
            </div>
        </section>

        <section class="section" id="privacy">
            <div class="section-header">
                <h2>Clear Data Handling.</h2>
                <p>The proxy stores only what it needs to queue, retry, protect, and count webhook delivery.</p>
            </div>
            <div class="privacy-grid">
                <article class="privacy-card">
                    <h3>Stored Permanently</h3>
                    <p>Aggregate counters, capped diagnostic events, and irreversible webhook fingerprints for the unique webhook counter.</p>
                </article>
                <article class="privacy-card">
                    <h3>Stored Temporarily</h3>
                    <p>Queued payloads, webhook tokens, source IPs, idempotency records, and retry metadata until delivery or expiry.</p>
                </article>
                <article class="privacy-card">
                    <h3>Processed In Transit</h3>
                    <p>Request bodies, content types, query strings, webhook IDs, Discord responses, and rate-limit headers.</p>
                </article>
            </div>
        </section>

        <section class="section" id="rules">
            <div class="section-header">
                <h2>Simple Use Guidelines.</h2>
                <p>Use the proxy kindly and responsibly so it stays reliable for everyone.</p>
            </div>
            <div class="rules-grid">
                <article class="rule-card">
                    <h3>No Spamming Or Flooding</h3>
                    <p>Do not intentionally overload Discord, Railway, Redis, this proxy, or any webhook.</p>
                </article>
                <article class="rule-card">
                    <h3>Use Webhooks You Own</h3>
                    <p>Only use Discord or proxy webhook URLs you created or are explicitly allowed to use.</p>
                </article>
                <article class="rule-card">
                    <h3>Respect Platform Rules</h3>
                    <p>No abuse, harassment, illegal content, credential leakage, or evasive automation.</p>
                </article>
            </div>
        </section>

        <footer class="footer">
            <span>Proxy Status: <strong class="online">Online</strong></span>
            <span class="credit">Architect: <strong>Yee Sen</strong><span>Discord: <strong>@yeetysenny</strong></span></span>
        </footer>
    </main>

    <script nonce="__NONCE__">
        const input = document.getElementById("webhook-input");
        const output = document.getElementById("webhook-output");
        const error = document.getElementById("error-msg");
        const copyButton = document.getElementById("copy-btn");
        const compileButton = document.getElementById("compile-btn");

        function isDiscordHostname(hostname) {
            const value = hostname.toLowerCase();
            return value === "discord.com" || value === "discordapp.com";
        }

        function convertWebhook() {
            try {
                const original = new URL(input.value.trim());
                if (original.protocol !== "https:" || !isDiscordHostname(original.hostname)) {
                    throw new Error("Invalid host");
                }
                if (!/^\/api\/webhooks\/\d+\/[A-Za-z0-9_-]+$/.test(original.pathname)) {
                    throw new Error("Invalid path");
                }

                const proxy = new URL(window.location.origin);
                proxy.pathname = original.pathname;
                proxy.search = original.search;
                output.value = proxy.toString();
                error.classList.remove("visible");
            } catch (_) {
                output.value = "";
                error.classList.add("visible");
            }
        }

        async function copyToClipboard() {
            if (!output.value) {
                return;
            }

            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(output.value);
            } else {
                output.select();
                document.execCommand("copy");
            }

            const oldText = copyButton.textContent;
            copyButton.textContent = "Copied";
            setTimeout(() => {
                copyButton.textContent = oldText;
            }, 1600);
        }

        function formatNumber(value) {
            return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value || 0);
        }

        function setCounter(id, value) {
            document.getElementById(id).textContent = formatNumber(value);
        }

        async function refreshStats() {
            try {
                const response = await fetch("/api/stats", { cache: "no-store" });
                if (!response.ok) {
                    return;
                }
                const stats = await response.json();
                setCounter("unique-webhooks", stats.unique_webhooks);
                setCounter("requests-served", stats.requests_served);
                setCounter("sent-count", stats.sent);
            } catch (_) {}
        }

        compileButton.addEventListener("click", convertWebhook);
        copyButton.addEventListener("click", copyToClipboard);
        input.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                convertWebhook();
            }
        });

        refreshStats();
        setInterval(refreshStats, 60000);
    </script>
</body>
</html>
"""


CLAIM_NEXT_JOB_LUA = """
local ready_key = KEYS[1]
local processing_key = KEYS[2]
local processing_meta_key = KEYS[3]
local global_backoff_key = KEYS[4]
local global_dispatch_window_key = KEYS[5]
local pending_jobs_key = KEYS[6]
local pending_bytes_key = KEYS[7]

local now_ms = tonumber(ARGV[1])
local scan_limit = tonumber(ARGV[2])
local consumer = ARGV[3]
local visibility_ms = tonumber(ARGV[4])
local queue_prefix = ARGV[5]
local job_prefix = ARGV[6]
local claim_prefix = ARGV[7]
local lock_prefix = ARGV[8]
local webhook_lock_prefix = ARGV[9]
local webhook_backoff_prefix = ARGV[10]
local webhook_pending_prefix = ARGV[11]
local webhook_bytes_prefix = ARGV[12]
local target_bytes_prefix = ARGV[13]
local cleanup_limit = tonumber(ARGV[14])
local global_requests_per_second = tonumber(ARGV[15])
local claim_token = ARGV[16]
local contention_delay_ms = tonumber(ARGV[17])

local function parse_entry(entry)
    local first = string.find(entry, '|', 1, true)
    if not first then
        return entry, 0, ''
    end
    local second = string.find(entry, '|', first + 1, true)
    if not second then
        return string.sub(entry, 1, first - 1), tonumber(string.sub(entry, first + 1)) or 0, ''
    end
    return string.sub(entry, 1, first - 1), tonumber(string.sub(entry, first + 1, second - 1)) or 0, string.sub(entry, second + 1)
end

local function decrement_counter(key, amount, delete_when_zero)
    if amount <= 0 then
        return
    end
    local value = tonumber(redis.call('GET', key) or '0') - amount
    if value <= 0 then
        if delete_when_zero == 1 then
            redis.call('DEL', key)
        else
            redis.call('SET', key, '0')
        end
    else
        redis.call('SET', key, tostring(value))
    end
end

local function decrement_entry(target_key, entry)
    local _, charge, webhook_key = parse_entry(entry)
    decrement_counter(pending_jobs_key, 1, 0)
    decrement_counter(pending_bytes_key, charge, 0)
    decrement_counter(target_bytes_prefix .. target_key, charge, 1)
    if webhook_key ~= '' then
        decrement_counter(webhook_pending_prefix .. webhook_key, 1, 1)
        decrement_counter(webhook_bytes_prefix .. webhook_key, charge, 1)
    end
end

local function promote_head(target_key)
    local queue_key = queue_prefix .. target_key
    local cleaned = 0
    while cleaned < cleanup_limit do
        local entry = redis.call('LINDEX', queue_key, 0)
        if not entry then
            redis.call('ZREM', ready_key, target_key)
            redis.call('DEL', queue_key)
            redis.call('DEL', target_bytes_prefix .. target_key)
            return nil
        end

        local job_id, _, entry_webhook_key = parse_entry(entry)
        local job_key = job_prefix .. job_id
        if redis.call('EXISTS', job_key) == 1 then
            local available_at = tonumber(redis.call('HGET', job_key, 'available_at_ms') or '0')
            local webhook_key = redis.call('HGET', job_key, 'webhook_key') or entry_webhook_key
            return {job_id, entry, webhook_key, available_at}
        end

        redis.call('LPOP', queue_key)
        decrement_entry(target_key, entry)
        cleaned = cleaned + 1
    end

    redis.call('ZADD', ready_key, now_ms, target_key)
    return nil
end

if redis.call('EXISTS', global_backoff_key) == 1 then
    return {}
end

local due_targets = redis.call('ZRANGEBYSCORE', ready_key, '-inf', now_ms, 'LIMIT', 0, scan_limit)

for _, target_key in ipairs(due_targets) do
    local head = promote_head(target_key)
    if head then
        local job_id = head[1]
        local entry = head[2]
        local webhook_key = head[3]
        local available_at = tonumber(head[4]) or 0

        if available_at > now_ms then
            redis.call('ZADD', ready_key, available_at, target_key)
        else
            local webhook_backoff_key = webhook_backoff_prefix .. webhook_key
            local webhook_backoff_ms = redis.call('PTTL', webhook_backoff_key)
            if webhook_backoff_ms and webhook_backoff_ms > 0 then
                redis.call('ZADD', ready_key, now_ms + webhook_backoff_ms, target_key)
            else
                local claim_value = job_id .. '|' .. claim_token
                local lock_key = lock_prefix .. target_key
                local webhook_lock_key = webhook_lock_prefix .. webhook_key
                if redis.call('SET', lock_key, claim_value, 'NX', 'PX', visibility_ms) then
                    if redis.call('SET', webhook_lock_key, claim_value, 'NX', 'PX', visibility_ms) then
                        local dispatch_allowed = 1
                        if global_requests_per_second > 0 then
                            local current = tonumber(redis.call('GET', global_dispatch_window_key) or '0')
                            local ttl = redis.call('PTTL', global_dispatch_window_key)
                            if ttl and ttl < 0 then
                                redis.call('DEL', global_dispatch_window_key)
                                current = 0
                                ttl = 0
                            end
                            if current >= global_requests_per_second and ttl and ttl > 0 then
                                dispatch_allowed = 0
                                redis.call('DEL', lock_key)
                                redis.call('DEL', webhook_lock_key)
                                redis.call('ZADD', ready_key, now_ms + ttl, target_key)
                            else
                                local count = redis.call('INCR', global_dispatch_window_key)
                                if count == 1 then
                                    redis.call('PEXPIRE', global_dispatch_window_key, 1000)
                                end
                            end
                        end

                        if dispatch_allowed == 1 then
                            local claim_key = claim_prefix .. job_id
                            redis.call('SET', claim_key, claim_value, 'PX', visibility_ms)
                            redis.call('ZADD', processing_key, now_ms + visibility_ms, job_id)
                            redis.call('HSET', processing_meta_key, job_id, target_key .. '\t' .. entry .. '\t' .. claim_token)
                            redis.call('ZREM', ready_key, target_key)
                            return {job_id, target_key, entry, webhook_key, claim_token, consumer}
                        end
                    else
                        redis.call('DEL', lock_key)
                        redis.call('ZADD', ready_key, now_ms + contention_delay_ms, target_key)
                    end
                end
            end
        end
    end
end

return {}
"""

FINALIZE_JOB_LUA = """
local ready_key = KEYS[1]
local processing_key = KEYS[2]
local processing_meta_key = KEYS[3]
local pending_jobs_key = KEYS[4]
local pending_bytes_key = KEYS[5]
local job_key = KEYS[6]
local queue_key = KEYS[7]
local claim_key = KEYS[8]
local lock_key = KEYS[9]
local webhook_pending_key = KEYS[10]
local webhook_bytes_key = KEYS[11]
local target_bytes_key = KEYS[12]
local webhook_lock_key = KEYS[13]
local result_key = KEYS[14]
local idempotency_key = KEYS[15]

local job_id = ARGV[1]
local target_key = ARGV[2]
local queue_entry = ARGV[3]
local webhook_key = ARGV[4]
local claim_token = ARGV[5]
local delete_job = ARGV[6]
local job_prefix = ARGV[7]
local queue_prefix = ARGV[8]
local claim_prefix = ARGV[9]
local lock_prefix = ARGV[10]
local webhook_pending_prefix = ARGV[11]
local webhook_bytes_prefix = ARGV[12]
local target_bytes_prefix = ARGV[13]
local cleanup_limit = tonumber(ARGV[14])
local now_ms = tonumber(ARGV[15])
local result_present = ARGV[16]
local result_ttl = tonumber(ARGV[17])
local result_status_code = ARGV[18]
local result_body_b64 = ARGV[19]
local result_content_type = ARGV[20]
local result_headers_json = ARGV[21]
local result_attempts = ARGV[22]
local result_kind = ARGV[23]
local result_message = ARGV[24]
local result_request_id = ARGV[25]
local has_idempotency_key = ARGV[26]

local function parse_entry(entry)
    local first = string.find(entry, '|', 1, true)
    if not first then
        return entry, 0, ''
    end
    local second = string.find(entry, '|', first + 1, true)
    if not second then
        return string.sub(entry, 1, first - 1), tonumber(string.sub(entry, first + 1)) or 0, ''
    end
    return string.sub(entry, 1, first - 1), tonumber(string.sub(entry, first + 1, second - 1)) or 0, string.sub(entry, second + 1)
end

local function meta_token(value)
    if not value then
        return ''
    end
    local last = nil
    local start = 1
    while true do
        local pos = string.find(value, '	', start, true)
        if not pos then
            return string.sub(value, start)
        end
        last = pos
        start = pos + 1
    end
end

local function decrement_counter(key, amount, delete_when_zero)
    if amount <= 0 then
        return
    end
    local value = tonumber(redis.call('GET', key) or '0') - amount
    if value <= 0 then
        if delete_when_zero == 1 then
            redis.call('DEL', key)
        else
            redis.call('SET', key, '0')
        end
    else
        redis.call('SET', key, tostring(value))
    end
end

local function decrement_entry(entry_target_key, entry)
    local _, charge, entry_webhook_key = parse_entry(entry)
    decrement_counter(pending_jobs_key, 1, 0)
    decrement_counter(pending_bytes_key, charge, 0)
    decrement_counter(target_bytes_prefix .. entry_target_key, charge, 1)
    if entry_webhook_key ~= '' then
        decrement_counter(webhook_pending_prefix .. entry_webhook_key, 1, 1)
        decrement_counter(webhook_bytes_prefix .. entry_webhook_key, charge, 1)
    end
end

local current_meta = redis.call('HGET', processing_meta_key, job_id)
if current_meta and meta_token(current_meta) ~= claim_token then
    return {'stale'}
end

local was_processing = redis.call('ZSCORE', processing_key, job_id)
local queue_removed = redis.call('LREM', queue_key, 1, queue_entry)
if queue_removed == 0 and queue_entry ~= job_id then
    queue_removed = redis.call('LREM', queue_key, 1, job_id)
end

local _, charge, entry_webhook_key = parse_entry(queue_entry)
if charge <= 0 then
    charge = tonumber(redis.call('HGET', job_key, 'storage_bytes') or '0')
end
if webhook_key == '' then
    webhook_key = redis.call('HGET', job_key, 'webhook_key') or entry_webhook_key
end

redis.call('ZREM', processing_key, job_id)
redis.call('HDEL', processing_meta_key, job_id)

local claim_value = job_id .. '|' .. claim_token
if redis.call('GET', claim_key) == claim_value then
    redis.call('DEL', claim_key)
end
if redis.call('GET', lock_key) == claim_value or redis.call('GET', lock_key) == job_id then
    redis.call('DEL', lock_key)
end
if redis.call('GET', webhook_lock_key) == claim_value or redis.call('GET', webhook_lock_key) == job_id then
    redis.call('DEL', webhook_lock_key)
end

if result_present == '1' then
    redis.call(
        'HSET',
        result_key,
        'status_code', result_status_code,
        'body_b64', result_body_b64,
        'content_type', result_content_type,
        'headers_json', result_headers_json,
        'attempts', result_attempts,
        'result_kind', result_kind,
        'result_message', result_message,
        'request_id', result_request_id
    )
    redis.call('EXPIRE', result_key, result_ttl)
    if has_idempotency_key == '1' and redis.call('EXISTS', idempotency_key) == 1 then
        redis.call('EXPIRE', idempotency_key, result_ttl)
    end
end

if delete_job == '1' then
    redis.call('DEL', job_key)
end

if queue_removed > 0 or was_processing then
    decrement_counter(pending_jobs_key, 1, 0)
    decrement_counter(pending_bytes_key, charge, 0)
    decrement_counter(target_bytes_key, charge, 1)
    if webhook_key ~= '' then
        decrement_counter(webhook_pending_key, 1, 1)
        decrement_counter(webhook_bytes_key, charge, 1)
    end
end

local cleaned = 0
while cleaned < cleanup_limit do
    local next_entry = redis.call('LINDEX', queue_key, 0)
    if not next_entry then
        redis.call('ZREM', ready_key, target_key)
        redis.call('DEL', queue_key)
        redis.call('DEL', target_bytes_key)
        return {'finalized'}
    end

    local next_job_id = parse_entry(next_entry)
    local next_job_key = job_prefix .. next_job_id
    if redis.call('EXISTS', next_job_key) == 1 then
        local next_available_at = tonumber(redis.call('HGET', next_job_key, 'available_at_ms') or tostring(now_ms))
        if next_available_at < now_ms then
            next_available_at = now_ms
        end
        redis.call('ZADD', ready_key, next_available_at, target_key)
        return {'finalized'}
    end

    redis.call('LPOP', queue_key)
    decrement_entry(target_key, next_entry)
    cleaned = cleaned + 1
end

redis.call('ZADD', ready_key, now_ms, target_key)
return {'finalized'}
"""

RESCHEDULE_JOB_LUA = """
local ready_key = KEYS[1]
local processing_key = KEYS[2]
local processing_meta_key = KEYS[3]
local job_key = KEYS[4]
local claim_key = KEYS[5]
local lock_key = KEYS[6]
local webhook_lock_key = KEYS[7]

local job_id = ARGV[1]
local target_key = ARGV[2]
local next_available_at = tonumber(ARGV[3])
local attempts = ARGV[4]
local last_error = ARGV[5]
local last_status = ARGV[6]
local job_ttl = tonumber(ARGV[7])
local claim_token = ARGV[8]

local meta = redis.call('HGET', processing_meta_key, job_id)
if meta then
    local last_tab = nil
    local start = 1
    while true do
        local pos = string.find(meta, '\t', start, true)
        if not pos then
            local token = string.sub(meta, start)
            if token ~= claim_token then
                return {'stale'}
            end
            break
        end
        last_tab = pos
        start = pos + 1
    end
end

if redis.call('EXISTS', job_key) == 0 then
    return {'missing'}
end

redis.call('HSET', job_key, 'attempts', attempts, 'available_at_ms', tostring(next_available_at), 'last_error', last_error, 'last_status', last_status)
redis.call('EXPIRE', job_key, job_ttl)
redis.call('ZREM', processing_key, job_id)
redis.call('HDEL', processing_meta_key, job_id)

local claim_value = job_id .. '|' .. claim_token
if redis.call('GET', claim_key) == claim_value then
    redis.call('DEL', claim_key)
end
if redis.call('GET', lock_key) == claim_value or redis.call('GET', lock_key) == job_id then
    redis.call('DEL', lock_key)
end
if redis.call('GET', webhook_lock_key) == claim_value or redis.call('GET', webhook_lock_key) == job_id then
    redis.call('DEL', webhook_lock_key)
end

redis.call('ZADD', ready_key, next_available_at, target_key)
return {'rescheduled'}
"""

RECLAIM_JOB_LUA = """
local ready_key = KEYS[1]
local processing_key = KEYS[2]
local processing_meta_key = KEYS[3]
local pending_jobs_key = KEYS[4]
local pending_bytes_key = KEYS[5]
local job_key = KEYS[6]
local claim_key = KEYS[7]

local job_id = ARGV[1]
local now_ms = tonumber(ARGV[2])
local job_ttl = tonumber(ARGV[3])
local queue_prefix = ARGV[4]
local job_prefix = ARGV[5]
local lock_prefix = ARGV[6]
local webhook_pending_prefix = ARGV[7]
local webhook_bytes_prefix = ARGV[8]
local target_bytes_prefix = ARGV[9]
local webhook_lock_prefix = ARGV[10]
local cleanup_limit = tonumber(ARGV[11])

local function parse_entry(entry)
    local first = string.find(entry, '|', 1, true)
    if not first then
        return entry, 0, ''
    end
    local second = string.find(entry, '|', first + 1, true)
    if not second then
        return string.sub(entry, 1, first - 1), tonumber(string.sub(entry, first + 1)) or 0, ''
    end
    return string.sub(entry, 1, first - 1), tonumber(string.sub(entry, first + 1, second - 1)) or 0, string.sub(entry, second + 1)
end

local function decrement_counter(key, amount, delete_when_zero)
    if amount <= 0 then
        return
    end
    local value = tonumber(redis.call('GET', key) or '0') - amount
    if value <= 0 then
        if delete_when_zero == 1 then
            redis.call('DEL', key)
        else
            redis.call('SET', key, '0')
        end
    else
        redis.call('SET', key, tostring(value))
    end
end

local function decrement_entry(target_key, entry)
    local _, charge, webhook_key = parse_entry(entry)
    decrement_counter(pending_jobs_key, 1, 0)
    decrement_counter(pending_bytes_key, charge, 0)
    decrement_counter(target_bytes_prefix .. target_key, charge, 1)
    if webhook_key ~= '' then
        decrement_counter(webhook_pending_prefix .. webhook_key, 1, 1)
        decrement_counter(webhook_bytes_prefix .. webhook_key, charge, 1)
    end
end

local score = redis.call('ZSCORE', processing_key, job_id)
if not score then
    return {'gone'}
end
if tonumber(score) > now_ms then
    return {'not_due'}
end

local claim_ttl = redis.call('PTTL', claim_key)
if claim_ttl and claim_ttl > 0 then
    redis.call('ZADD', processing_key, now_ms + claim_ttl, job_id)
    return {'active'}
end

local meta = redis.call('HGET', processing_meta_key, job_id) or ''
local first_tab = string.find(meta, '\t', 1, true)
local last_tab = nil
local target_key = ''
local queue_entry = ''
local claim_token = ''

if first_tab then
    target_key = string.sub(meta, 1, first_tab - 1)
    local second_tab = string.find(meta, '\t', first_tab + 1, true)
    if second_tab then
        queue_entry = string.sub(meta, first_tab + 1, second_tab - 1)
        claim_token = string.sub(meta, second_tab + 1)
    end
end

if target_key == '' then
    target_key = redis.call('HGET', job_key, 'target_key') or redis.call('HGET', job_key, 'webhook_key') or ''
end
if queue_entry == '' then
    queue_entry = redis.call('HGET', job_key, 'queue_entry') or job_id
end

if target_key == '' then
    redis.call('ZREM', processing_key, job_id)
    redis.call('HDEL', processing_meta_key, job_id)
    redis.call('DEL', claim_key)
    return {'orphaned'}
end

local _, _, entry_webhook_key = parse_entry(queue_entry)
local webhook_key = redis.call('HGET', job_key, 'webhook_key') or entry_webhook_key
local queue_key = queue_prefix .. target_key
local lock_key = lock_prefix .. target_key
local webhook_lock_key = webhook_lock_prefix .. webhook_key
local claim_value = job_id .. '|' .. claim_token

if redis.call('EXISTS', job_key) == 1 then
    redis.call('HSET', job_key, 'available_at_ms', tostring(now_ms), 'last_error', 'reclaimed_after_visibility_timeout')
    redis.call('EXPIRE', job_key, job_ttl)
    if redis.call('GET', lock_key) == claim_value or redis.call('GET', lock_key) == job_id then
        redis.call('DEL', lock_key)
    end
    if webhook_key ~= '' and (redis.call('GET', webhook_lock_key) == claim_value or redis.call('GET', webhook_lock_key) == job_id) then
        redis.call('DEL', webhook_lock_key)
    end
    redis.call('ZREM', processing_key, job_id)
    redis.call('HDEL', processing_meta_key, job_id)
    redis.call('DEL', claim_key)
    redis.call('ZADD', ready_key, now_ms, target_key)
    return {'reclaimed'}
end

local removed = redis.call('LREM', queue_key, 1, queue_entry)
if removed == 0 and queue_entry ~= job_id then
    removed = redis.call('LREM', queue_key, 1, job_id)
end
if removed > 0 then
    decrement_entry(target_key, queue_entry)
end

if redis.call('GET', lock_key) == claim_value or redis.call('GET', lock_key) == job_id then
    redis.call('DEL', lock_key)
end
if webhook_key ~= '' and (redis.call('GET', webhook_lock_key) == claim_value or redis.call('GET', webhook_lock_key) == job_id) then
    redis.call('DEL', webhook_lock_key)
end
redis.call('ZREM', processing_key, job_id)
redis.call('HDEL', processing_meta_key, job_id)
redis.call('DEL', claim_key)

local cleaned = 0
while cleaned < cleanup_limit do
    local next_entry = redis.call('LINDEX', queue_key, 0)
    if not next_entry then
        redis.call('ZREM', ready_key, target_key)
        redis.call('DEL', queue_key)
        redis.call('DEL', target_bytes_prefix .. target_key)
        return {'missing_cleaned'}
    end
    local next_job_id = parse_entry(next_entry)
    if redis.call('EXISTS', job_prefix .. next_job_id) == 1 then
        local available_at = tonumber(redis.call('HGET', job_prefix .. next_job_id, 'available_at_ms') or tostring(now_ms))
        if available_at < now_ms then
            available_at = now_ms
        end
        redis.call('ZADD', ready_key, available_at, target_key)
        return {'missing_cleaned'}
    end
    redis.call('LPOP', queue_key)
    decrement_entry(target_key, next_entry)
    cleaned = cleaned + 1
end

redis.call('ZADD', ready_key, now_ms, target_key)
return {'missing_cleaned'}
"""

RATE_LIMIT_LUA = """
local window_key = KEYS[1]
local violations_key = KEYS[2]
local block_key = KEYS[3]
local global_window_key = KEYS[4]
local limit = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local violation_ttl = tonumber(ARGV[3])
local block_after = tonumber(ARGV[4])
local base_block_seconds = tonumber(ARGV[5])
local max_block_seconds = tonumber(ARGV[6])
local burst_multiplier = tonumber(ARGV[7])
local global_limit = tonumber(ARGV[8])
local global_window_seconds = tonumber(ARGV[9])

local global_count = redis.call('INCR', global_window_key)
if global_count == 1 then
    redis.call('EXPIRE', global_window_key, global_window_seconds)
end
if global_count > global_limit then
    local global_ttl = redis.call('TTL', global_window_key)
    if not global_ttl or global_ttl < 1 then
        global_ttl = global_window_seconds
        redis.call('EXPIRE', global_window_key, global_window_seconds)
    end
    return {0, global_ttl, 0, global_count, global_limit}
end

local block_ttl = redis.call('TTL', block_key)
if block_ttl and block_ttl > 0 then
    return {0, block_ttl, 1, 0, limit}
end

local count = redis.call('INCR', window_key)
if count == 1 then
    redis.call('EXPIRE', window_key, window_seconds)
end

if count <= limit then
    return {1, 0, 0, count, limit}
end

local window_ttl = redis.call('TTL', window_key)
if not window_ttl or window_ttl < 1 then
    window_ttl = window_seconds
    redis.call('EXPIRE', window_key, window_seconds)
end

local violations = redis.call('INCR', violations_key)
redis.call('EXPIRE', violations_key, violation_ttl)

local should_block = 0
if violations >= block_after then
    should_block = 1
end
if count >= math.floor(limit * burst_multiplier) then
    should_block = 1
end

if should_block == 1 then
    local exponent = violations - block_after
    if exponent < 0 then
        exponent = 0
    end
    if exponent > 8 then
        exponent = 8
    end
    local duration = base_block_seconds * (2 ^ exponent)
    local over_ratio = math.floor(count / limit)
    if over_ratio > 1 then
        duration = duration + (base_block_seconds * over_ratio)
    end
    if duration < window_ttl then
        duration = window_ttl
    end
    if duration > max_block_seconds then
        duration = max_block_seconds
    end
    redis.call('SETEX', block_key, duration, tostring(violations))
    return {0, duration, 1, count, limit}
end

return {0, window_ttl, 0, count, limit}
"""

ENQUEUE_JOB_LUA = """
local job_key = KEYS[1]
local queue_key = KEYS[2]
local ready_key = KEYS[3]
local pending_jobs_key = KEYS[4]
local pending_bytes_key = KEYS[5]
local webhook_pending_key = KEYS[6]
local webhook_bytes_key = KEYS[7]
local target_bytes_key = KEYS[8]
local unique_hll_key = KEYS[9]
local stats_key = KEYS[10]
local idem_key = KEYS[11]
local idem_index_key = KEYS[12]

local job_id = ARGV[1]
local request_id = ARGV[2]
local webhook_id = ARGV[3]
local webhook_token = ARGV[4]
local webhook_key = ARGV[5]
local target_key = ARGV[6]
local target_context = ARGV[7]
local query_string = ARGV[8]
local body_b64 = ARGV[9]
local content_type = ARGV[10]
local created_at_ms = ARGV[11]
local body_sha256 = ARGV[12]
local request_sha256 = ARGV[13]
local idempotency_value = ARGV[14]
local job_ttl = tonumber(ARGV[15])
local idempotency_ttl = tonumber(ARGV[16])
local storage_bytes = tonumber(ARGV[17])
local priority = ARGV[18]
local target_limit = tonumber(ARGV[19])
local webhook_limit = tonumber(ARGV[20])
local global_limit = tonumber(ARGV[21])
local target_bytes_limit = tonumber(ARGV[22])
local webhook_bytes_limit = tonumber(ARGV[23])
local global_bytes_limit = tonumber(ARGV[24])
local absolute_limit = tonumber(ARGV[25])
local absolute_bytes_limit = tonumber(ARGV[26])
local idempotency_max_entries = tonumber(ARGV[27])
local idempotency_cleanup_limit = tonumber(ARGV[28])

if idempotency_value ~= '' then
    local expired_idempotency_keys = redis.call(
        'ZRANGEBYSCORE',
        idem_index_key,
        '-inf',
        tonumber(created_at_ms),
        'LIMIT',
        0,
        idempotency_cleanup_limit
    )
    for _, expired_idempotency_key in ipairs(expired_idempotency_keys) do
        redis.call('ZREM', idem_index_key, expired_idempotency_key)
        redis.call('DEL', expired_idempotency_key)
    end
    local existing_request_sha256 = redis.call('HGET', idem_key, 'request_sha256') or ''
    local existing_body_sha256 = redis.call('HGET', idem_key, 'body_sha256') or ''
    if existing_request_sha256 ~= '' or existing_body_sha256 ~= '' then
        local existing_request_id = redis.call('HGET', idem_key, 'request_id') or ''
        local existing_job_id = redis.call('HGET', idem_key, 'job_id') or ''
        if existing_request_sha256 ~= '' then
            if existing_request_sha256 ~= request_sha256 then
                return {'conflict', existing_request_id, existing_job_id, '0', '0'}
            end
        elseif existing_body_sha256 ~= body_sha256 then
            return {'conflict', existing_request_id, existing_job_id, '0', '0'}
        end
        redis.call('HINCRBY', stats_key, 'duplicates', 1)
        redis.call('PFADD', unique_hll_key, webhook_key)
        return {'duplicate', existing_request_id, existing_job_id, '0', '0'}
    end

    local idempotency_count = redis.call('ZCARD', idem_index_key)
    if idempotency_count >= idempotency_max_entries then
        local overflow = idempotency_count - idempotency_max_entries + 1
        local remove_count = overflow
        if remove_count > idempotency_cleanup_limit then
            remove_count = idempotency_cleanup_limit
        end
        local oldest_idempotency_keys = redis.call('ZRANGE', idem_index_key, 0, remove_count - 1)
        for _, oldest_idempotency_key in ipairs(oldest_idempotency_keys) do
            redis.call('ZREM', idem_index_key, oldest_idempotency_key)
            redis.call('DEL', oldest_idempotency_key)
        end
        if redis.call('ZCARD', idem_index_key) >= idempotency_max_entries then
            return {'global_idempotency_overloaded', request_id, job_id, '0', '0'}
        end
    end
end

local queue_length = redis.call('LLEN', queue_key)
local pending_jobs = tonumber(redis.call('GET', pending_jobs_key) or '0')
local pending_bytes = tonumber(redis.call('GET', pending_bytes_key) or '0')
local webhook_pending = tonumber(redis.call('GET', webhook_pending_key) or '0')
local webhook_bytes = tonumber(redis.call('GET', webhook_bytes_key) or '0')
local target_bytes = tonumber(redis.call('GET', target_bytes_key) or '0')

if absolute_limit > 0 and pending_jobs + 1 > absolute_limit then
    return {'absolute_count_overloaded', request_id, job_id, tostring(queue_length), tostring(pending_jobs)}
end
if absolute_bytes_limit > 0 and pending_bytes + storage_bytes > absolute_bytes_limit then
    return {'absolute_bytes_overloaded', request_id, job_id, tostring(queue_length), tostring(pending_jobs)}
end

if priority ~= '1' then
    if target_limit > 0 and queue_length + 1 > target_limit then
        return {'target_count_overloaded', request_id, job_id, tostring(queue_length), tostring(pending_jobs)}
    end
    if webhook_limit > 0 and webhook_pending + 1 > webhook_limit then
        return {'webhook_count_overloaded', request_id, job_id, tostring(queue_length), tostring(pending_jobs)}
    end
    if global_limit > 0 and pending_jobs + 1 > global_limit then
        return {'global_count_overloaded', request_id, job_id, tostring(queue_length), tostring(pending_jobs)}
    end
    if target_bytes_limit > 0 and target_bytes + storage_bytes > target_bytes_limit then
        return {'target_bytes_overloaded', request_id, job_id, tostring(queue_length), tostring(pending_jobs)}
    end
    if webhook_bytes_limit > 0 and webhook_bytes + storage_bytes > webhook_bytes_limit then
        return {'webhook_bytes_overloaded', request_id, job_id, tostring(queue_length), tostring(pending_jobs)}
    end
    if global_bytes_limit > 0 and pending_bytes + storage_bytes > global_bytes_limit then
        return {'global_bytes_overloaded', request_id, job_id, tostring(queue_length), tostring(pending_jobs)}
    end
end

local queue_entry = job_id .. '|' .. tostring(storage_bytes) .. '|' .. webhook_key

redis.call(
    'HSET',
    job_key,
    'job_id', job_id,
    'request_id', request_id,
    'webhook_id', webhook_id,
    'webhook_token', webhook_token,
    'webhook_key', webhook_key,
    'target_key', target_key,
    'target_context', target_context,
    'queue_entry', queue_entry,
    'query_string', query_string,
    'body_b64', body_b64,
    'content_type', content_type,
    'created_at_ms', created_at_ms,
    'available_at_ms', created_at_ms,
    'attempts', '0',
    'last_error', '',
    'last_status', '',
    'body_sha256', body_sha256,
    'request_sha256', request_sha256,
    'storage_bytes', tostring(storage_bytes),
    'priority', priority,
    'idempotency_redis_key', idem_key
)
redis.call('EXPIRE', job_key, job_ttl)

queue_length = redis.call('RPUSH', queue_key, queue_entry)
redis.call('PERSIST', queue_key)
redis.call('INCR', pending_jobs_key)
redis.call('INCRBY', pending_bytes_key, storage_bytes)
redis.call('INCR', webhook_pending_key)
redis.call('INCRBY', webhook_bytes_key, storage_bytes)
redis.call('INCRBY', target_bytes_key, storage_bytes)
redis.call('PFADD', unique_hll_key, webhook_key)

if queue_length == 1 then
    redis.call('ZADD', ready_key, tonumber(created_at_ms), target_key)
end

if idempotency_value ~= '' then
    redis.call(
        'HSET',
        idem_key,
        'job_id', job_id,
        'request_id', request_id,
        'body_sha256', body_sha256,
        'request_sha256', request_sha256,
        'created_at_ms', created_at_ms
    )
    redis.call('EXPIRE', idem_key, idempotency_ttl)
    redis.call('ZADD', idem_index_key, tonumber(created_at_ms) + (idempotency_ttl * 1000), idem_key)
end

redis.call('HINCRBY', stats_key, 'accepted', 1)

return {'accepted', request_id, job_id, tostring(queue_length), tostring(pending_jobs + 1)}
"""

SET_MAX_BACKOFF_LUA = """
local key = KEYS[1]
local ttl_ms = tonumber(ARGV[1])
local current = redis.call('PTTL', key)
if not current or current < ttl_ms then
    redis.call('PSETEX', key, ttl_ms, '1')
    return ttl_ms
end
return current
"""

RECORD_INVALID_REQUEST_LUA = """
local window_key = KEYS[1]
local global_backoff_key = KEYS[2]
local stats_key = KEYS[3]

local request_limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])

local count = redis.call('INCR', window_key)
if count == 1 then
    redis.call('PEXPIRE', window_key, window_ms)
end
local ttl_ms = redis.call('PTTL', window_key)
if not ttl_ms or ttl_ms < 1 then
    ttl_ms = window_ms
    redis.call('PEXPIRE', window_key, window_ms)
end
redis.call('HINCRBY', stats_key, 'invalid_requests', 1)

if count >= request_limit then
    local current_backoff = redis.call('PTTL', global_backoff_key)
    if not current_backoff or current_backoff < ttl_ms then
        redis.call('PSETEX', global_backoff_key, ttl_ms, '1')
    end
    return {count, ttl_ms, 1}
end

return {count, ttl_ms, 0}
"""



def env_value(name: str, default: str = "", legacy_names: tuple[str, ...] = ()) -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    for legacy_name in legacy_names:
        legacy_value = os.getenv(legacy_name)
        if legacy_value is not None:
            return legacy_value
    return default




def get_int_env(name: str, default: int, legacy_names: tuple[str, ...] = ()) -> int:
    try:
        return int(env_value(name, str(default), legacy_names))
    except ValueError:
        return default


def get_float_env(name: str, default: float, legacy_names: tuple[str, ...] = ()) -> float:
    try:
        return float(env_value(name, str(default), legacy_names))
    except ValueError:
        return default


def get_csv_float_env(name: str, default: tuple[float, ...], legacy_names: tuple[str, ...] = ()) -> tuple[float, ...]:
    raw = env_value(name, ",".join(str(value) for value in default), legacy_names)
    values: list[float] = []
    for item in raw.split(","):
        try:
            parsed = float(item.strip())
        except ValueError:
            continue
        if parsed >= 0:
            values.append(parsed)
    return tuple(values) or default


def csv_items(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def is_discord_hostname(hostname: str) -> bool:
    return hostname.lower() in {"discord.com", "discordapp.com"}


def parse_webhook_url(value: str) -> tuple[str, str] | None:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or not is_discord_hostname(parsed.hostname):
        return None
    match = WEBHOOK_PATH_RE.fullmatch(parsed.path)
    if not match:
        return None
    return match.group(1), match.group(2)


def parse_blacklisted_webhooks(raw: str) -> set[str]:
    blocked: set[str] = set()
    for item in csv_items(raw):
        parsed = parse_webhook_url(item)
        if parsed:
            blocked.add(webhook_key(parsed[0], parsed[1]))
    return blocked


class Config:
    def __init__(self) -> None:
        self.redis_url = env_value("RedisUrl", "", ("REDIS_URL",)).strip()
        self.api_key = env_value("ApiKey", "", ("API_KEY",)).strip()
        self.port = max(1, get_int_env("Port", 8000, ("PORT",)))
        self.queue_prefix = env_value("QueuePrefix", "discord_proxy", ("QUEUE_PREFIX",)).strip() or "discord_proxy"
        self.dispatch_concurrency = max(1, get_int_env("DispatchConcurrency", 8, ("DISPATCH_CONCURRENCY",)))
        self.queue_scan_limit = max(1, get_int_env("QueueScanLimit", 64, ("QUEUE_SCAN_LIMIT",)))
        self.stale_cleanup_limit = max(1, min(256, get_int_env("StaleCleanupLimit", 16, ("STALE_CLEANUP_LIMIT",))))
        self.poll_interval_seconds = max(0.05, get_float_env("QueuePollIntervalSeconds", 0.25, ("QUEUE_POLL_INTERVAL_SECONDS",)))
        self.reclaim_interval_seconds = max(1.0, get_float_env("ReclaimIntervalSeconds", 10.0, ("RECLAIM_INTERVAL_SECONDS",)))
        self.http_timeout_seconds = max(5.0, get_float_env("HttpTimeoutSeconds", 20.0, ("HTTP_TIMEOUT_SECONDS",)))
        self.claim_visibility_seconds = max(
            self.http_timeout_seconds + 30.0,
            get_float_env("ClaimVisibilitySeconds", 120.0, ("CLAIM_VISIBILITY_SECONDS",)),
        )
        self.redis_health_check_interval_seconds = max(5, get_int_env("RedisHealthCheckIntervalSeconds", 15, ("REDIS_HEALTH_CHECK_INTERVAL_SECONDS",)))
        self.redis_socket_connect_timeout_seconds = max(1.0, get_float_env("RedisSocketConnectTimeoutSeconds", 5.0, ("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",)))
        self.redis_socket_timeout_seconds = max(2.0, get_float_env("RedisSocketTimeoutSeconds", 30.0, ("REDIS_SOCKET_TIMEOUT_SECONDS",)))
        self.max_retries = max(0, get_int_env("MaxRetries", 4, ("MAX_RETRIES", "MAX_ATTEMPTS")))
        self.retry_backoff_multiplier = max(1.0, get_float_env("RetryBackoffMultiplier", 2.0, ("RETRY_BACKOFF_MULTIPLIER",)))
        self.retry_schedule_seconds = get_csv_float_env("RetryScheduleSeconds", (1.0, 5.0, 30.0, 300.0), ("RETRY_SCHEDULE_SECONDS",))
        self.max_retry_delay_seconds = max(1.0, get_float_env("MaxRetryDelaySeconds", 300.0, ("MAX_RETRY_DELAY_SECONDS", "MAX_RETRY_SECONDS")))
        self.job_ttl_seconds = max(600, get_int_env("JobTtlSeconds", 604800, ("JOB_TTL_SECONDS",)))
        self.idempotency_ttl_seconds = max(60, get_int_env("IdempotencyTtlSeconds", 86400, ("IDEMPOTENCY_TTL_SECONDS",)))
        self.idempotency_max_entries = max(1, get_int_env("IdempotencyMaxEntries", 100000, ("IDEMPOTENCY_MAX_ENTRIES",)))
        self.idempotency_cleanup_limit = max(1, min(1000, get_int_env("IdempotencyCleanupLimit", 100, ("IDEMPOTENCY_CLEANUP_LIMIT",))))
        self.result_ttl_seconds = max(5, get_int_env("ResultTtlSeconds", 15, ("RESULT_TTL_SECONDS",)))
        self.result_poll_interval_seconds = max(0.01, get_float_env("ResultPollIntervalSeconds", 0.05, ("RESULT_POLL_INTERVAL_SECONDS",)))
        self.max_upstream_response_bytes = max(1024, get_int_env("MaxUpstreamResponseBytes", 256 * 1024, ("MAX_UPSTREAM_RESPONSE_BYTES",)))
        retry_wait_budget = (
            (self.max_retries + 1) * self.http_timeout_seconds
            + sum(retry_delay_seconds(index, self) for index in range(1, self.max_retries + 1))
            + 15.0
        )
        self.caller_wait_timeout_seconds = max(
            self.http_timeout_seconds,
            get_float_env("CallerWaitTimeoutSeconds", retry_wait_budget, ("CALLER_WAIT_TIMEOUT_SECONDS",)),
        )
        self.max_body_bytes = max(1024, get_int_env("MaxBodyBytes", 32 * 1024 * 1024, ("MAX_BODY_BYTES",)))
        self.storage_overhead_bytes = max(1024, get_int_env("StorageOverheadBytes", 2048, ("STORAGE_OVERHEAD_BYTES",)))
        self.max_query_length = max(256, get_int_env("MaxQueryLength", 8192, ("MAX_QUERY_LENGTH",)))
        self.max_query_fields = max(1, get_int_env("MaxQueryFields", 64, ("MAX_QUERY_FIELDS",)))
        self.max_idempotency_key_length = max(16, get_int_env("MaxIdempotencyKeyLength", 128, ("MAX_IDEMPOTENCY_KEY_LENGTH",)))
        self.max_content_type_length = max(32, get_int_env("MaxContentTypeLength", 200, ("MAX_CONTENT_TYPE_LENGTH",)))
        self.ingress_concurrency = max(1, get_int_env("IngressConcurrency", 64, ("INGRESS_CONCURRENCY",)))
        self.ingress_wait_seconds = max(0.001, get_float_env("IngressWaitSeconds", 0.05, ("INGRESS_WAIT_SECONDS",)))
        self.http_max_keepalive_connections = max(10, get_int_env("HttpMaxKeepaliveConnections", 200, ("HTTP_MAX_KEEPALIVE_CONNECTIONS",)))
        self.http_max_connections = max(self.http_max_keepalive_connections, get_int_env("HttpMaxConnections", 400, ("HTTP_MAX_CONNECTIONS",)))
        self.target_queue_limit = max(1, get_int_env("TargetQueueLimit", 1000, ("TARGET_QUEUE_LIMIT",)))
        self.webhook_queue_limit = max(1, get_int_env("WebhookQueueLimit", 1000, ("WEBHOOK_QUEUE_LIMIT",)))
        self.global_queue_limit = max(1, get_int_env("GlobalQueueLimit", 100000, ("GLOBAL_QUEUE_LIMIT",)))
        self.absolute_queue_limit = max(self.global_queue_limit, get_int_env("AbsoluteQueueLimit", 120000, ("ABSOLUTE_QUEUE_LIMIT",)))
        minimum_queue_bytes = (self.max_body_bytes * 4 // 3) + 4096
        self.target_queue_bytes_limit = max(minimum_queue_bytes, get_int_env("TargetQueueBytesLimit", 128 * 1024 * 1024, ("TARGET_QUEUE_BYTES_LIMIT",)))
        self.webhook_queue_bytes_limit = max(self.target_queue_bytes_limit, get_int_env("WebhookQueueBytesLimit", 256 * 1024 * 1024, ("WEBHOOK_QUEUE_BYTES_LIMIT",)))
        self.global_queue_bytes_limit = max(self.webhook_queue_bytes_limit, get_int_env("GlobalQueueBytesLimit", 512 * 1024 * 1024, ("GLOBAL_QUEUE_BYTES_LIMIT",)))
        self.absolute_queue_bytes_limit = max(self.global_queue_bytes_limit, get_int_env("AbsoluteQueueBytesLimit", 768 * 1024 * 1024, ("ABSOLUTE_QUEUE_BYTES_LIMIT",)))
        self.overload_retry_after_seconds = max(1, get_int_env("OverloadRetryAfterSeconds", 60, ("OVERLOAD_RETRY_AFTER_SECONDS",)))
        self.discord_global_requests_per_second = max(1, get_int_env("DiscordGlobalRequestsPerSecond", 45, ("DISCORD_GLOBAL_REQUESTS_PER_SECOND",)))
        self.discord_invalid_request_limit = max(1, get_int_env("DiscordInvalidRequestLimit", 9000, ("DISCORD_INVALID_REQUEST_LIMIT",)))
        self.discord_invalid_request_window_seconds = max(60, get_int_env("DiscordInvalidRequestWindowSeconds", 600, ("DISCORD_INVALID_REQUEST_WINDOW_SECONDS",)))
        self.global_ingress_rate_limit_requests = max(1, get_int_env("GlobalIngressRateLimitRequests", 10000, ("GLOBAL_INGRESS_RATE_LIMIT_REQUESTS",)))
        self.global_ingress_rate_limit_window_seconds = max(1, get_int_env("GlobalIngressRateLimitWindowSeconds", 60, ("GLOBAL_INGRESS_RATE_LIMIT_WINDOW_SECONDS",)))
        self.webhook_rate_limit_requests = max(1, get_int_env("WebhookRateLimitRequests", 120, ("WEBHOOK_RATE_LIMIT_REQUESTS",)))
        self.webhook_rate_limit_window_seconds = max(1, get_int_env("WebhookRateLimitWindowSeconds", 60, ("WEBHOOK_RATE_LIMIT_WINDOW_SECONDS",)))
        self.webhook_abuse_block_after = max(1, get_int_env("WebhookAbuseBlockAfter", 3, ("WEBHOOK_ABUSE_BLOCK_AFTER",)))
        self.webhook_abuse_base_block_seconds = max(1, get_int_env("WebhookAbuseBaseBlockSeconds", 30, ("WEBHOOK_ABUSE_BASE_BLOCK_SECONDS",)))
        self.webhook_abuse_max_block_seconds = min(3600, max(self.webhook_abuse_base_block_seconds, get_int_env("WebhookAbuseMaxBlockSeconds", 3600, ("WEBHOOK_ABUSE_MAX_BLOCK_SECONDS",))))
        self.webhook_abuse_burst_multiplier = max(1.0, get_float_env("WebhookAbuseBurstMultiplier", 2.0, ("WEBHOOK_ABUSE_BURST_MULTIPLIER",)))
        self.rate_limit_violation_ttl_seconds = max(60, get_int_env("RateLimitViolationTtlSeconds", 3600, ("RATE_LIMIT_VIOLATION_TTL_SECONDS",)))
        self.blacklisted_webhook_keys = parse_blacklisted_webhooks(
            env_value("BlacklistedWebhooks", "", ("BLACKLISTED_WEBHOOKS",))
        )

        if not self.redis_url:
            raise RuntimeError("RedisUrl is required for durable replica-safe dispatching.")


def now_ms() -> int:
    return int(time.time() * 1000)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def webhook_key(webhook_id: str, webhook_token: str) -> str:
    return sha256_text(f"{webhook_id}:{webhook_token}")


def target_key(webhook_key_value: str, target_context: str) -> str:
    if target_context == "webhook":
        return webhook_key_value
    return sha256_text(f"{webhook_key_value}:{target_context}")


def build_discord_url(webhook_id: str, webhook_token: str, query_string: str) -> str:
    base = f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}"
    return f"{base}?{query_string}" if query_string else base


def encode_body(body: bytes) -> str:
    return base64.b64encode(body).decode("ascii")


def decode_body(body_b64: str) -> bytes:
    return base64.b64decode(body_b64.encode("ascii"), validate=True)


def normalize_content_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def looks_like_json(body: bytes) -> bool:
    stripped = body.lstrip()
    return stripped.startswith(b"{") or stripped.startswith(b"[")


def parse_retry_after_header(value: str) -> float | None:
    try:
        return max(float(value), 0.0)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max((parsed - datetime.now(timezone.utc)).total_seconds(), 0.0)


def get_retry_after_seconds(response: httpx.Response) -> float:
    try:
        payload = response.json()
        retry_after = payload.get("retry_after")
        if retry_after is not None:
            return max(float(retry_after), 0.0)
    except (ValueError, TypeError, AttributeError):
        pass

    header_value = response.headers.get("Retry-After")
    if header_value:
        parsed_header = parse_retry_after_header(header_value)
        if parsed_header is not None:
            return parsed_header

    reset_after = response.headers.get("X-RateLimit-Reset-After")
    if reset_after:
        try:
            return max(float(reset_after), 0.0)
        except ValueError:
            pass

    return 1.0


def get_bucket_reset_after_seconds(response: httpx.Response) -> float | None:
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is None:
        return None
    try:
        if int(float(remaining)) > 0:
            return None
    except ValueError:
        return None
    reset_after = response.headers.get("X-RateLimit-Reset-After")
    if not reset_after:
        return None
    try:
        return max(float(reset_after), 0.0)
    except ValueError:
        return None


def is_global_rate_limited(response: httpx.Response) -> bool:
    if response.headers.get("X-RateLimit-Global", "").lower() == "true":
        return True
    if response.headers.get("X-RateLimit-Scope", "").lower() == "global":
        return True
    try:
        return bool(response.json().get("global") is True)
    except (ValueError, TypeError, AttributeError):
        return False


def truncate_text(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def upstream_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() in FORWARDED_UPSTREAM_HEADERS
    }


def proxy_delivery_result(
    status_code: int,
    code: str,
    message: str,
    attempts: int,
    request_id: str,
) -> dict[str, str]:
    body = json.dumps(
        {
            "message": message,
            "code": code,
            "request_id": request_id,
            "attempts": attempts,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        "status_code": str(status_code),
        "body_b64": encode_body(body),
        "content_type": "application/json",
        "headers_json": "{}",
        "attempts": str(attempts),
        "result_kind": "proxy",
        "result_message": message,
        "request_id": request_id,
    }


def upstream_delivery_result(
    response: httpx.Response,
    attempts: int,
    request_id: str,
    max_response_bytes: int,
) -> dict[str, str]:
    body = response.content
    if len(body) > max_response_bytes:
        return proxy_delivery_result(
            status.HTTP_502_BAD_GATEWAY,
            "upstream_response_too_large",
            f"Discord returned a response larger than the configured {max_response_bytes}-byte relay limit.",
            attempts,
            request_id,
        )
    content_type = response.headers.get("content-type", "")
    if not body and response.status_code >= 400:
        body = json.dumps(
            {
                "message": f"Discord returned HTTP {response.status_code} without a response body.",
                "code": None,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        content_type = "application/json"
    return {
        "status_code": str(response.status_code),
        "body_b64": encode_body(body),
        "content_type": content_type,
        "headers_json": json.dumps(upstream_headers(response), separators=(",", ":")),
        "attempts": str(attempts),
        "result_kind": "discord",
        "result_message": truncate_text(response.text.strip(), 500) if response.text else "",
        "request_id": request_id,
    }


def delivery_response(result: dict[str, str], fallback_request_id: str) -> Response:
    try:
        status_code = int(result["status_code"])
        if status_code < 100 or status_code > 599:
            raise ValueError
        body = decode_body(result.get("body_b64", ""))
        parsed_headers = json.loads(result.get("headers_json", "{}"))
        if not isinstance(parsed_headers, dict):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "message": "The proxy received an invalid terminal delivery result.",
                "code": "invalid_delivery_result",
                "request_id": fallback_request_id,
            },
        )

    headers = {
        str(name): str(value)
        for name, value in parsed_headers.items()
        if str(name).lower() in FORWARDED_UPSTREAM_HEADERS
    }
    content_type = result.get("content_type", "").strip()
    if content_type and not any(ord(character) < 32 or ord(character) == 127 for character in content_type):
        headers["Content-Type"] = content_type
    request_id = result.get("request_id") or fallback_request_id
    headers["X-Proxy-Request-Id"] = request_id
    headers["X-Proxy-Attempts"] = str(max(1, int(result.get("attempts", "1") or "1")))
    headers["X-Proxy-Result"] = result.get("result_kind", "unknown")
    return Response(content=body, status_code=status_code, headers=headers)


def retry_delay_seconds(failure_number: int, config: Config, server_retry_after: float | None = None) -> float:
    index = max(failure_number - 1, 0)
    if index < len(config.retry_schedule_seconds):
        delay = config.retry_schedule_seconds[index]
    else:
        extra_steps = index - len(config.retry_schedule_seconds) + 1
        delay = config.retry_schedule_seconds[-1] * (config.retry_backoff_multiplier ** extra_steps)
    delay = min(delay, config.max_retry_delay_seconds)
    if server_retry_after is not None:
        delay = max(delay, server_retry_after)
    jitter_seed = (failure_number * 9301 + 49297) % 233280
    jitter = (jitter_seed / 233280.0) * 0.25
    return delay + jitter


def integer_dict(values: dict[str, str]) -> dict[str, int]:
    converted: dict[str, int] = {}
    for key, value in values.items():
        try:
            converted[key] = int(value)
        except (TypeError, ValueError):
            converted[key] = 0
    return converted


def validate_content_type(content_type: str, max_length: int) -> str:
    value = content_type.strip()
    if len(value) > max_length:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content-Type header too large.")
    if any(ord(character) < 32 and character not in {"\t"} for character in value) or "\x7f" in value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Content-Type header.")
    return value


def sanitize_query_string(raw_query: str, config: Config, header_api_key: str | None) -> tuple[str, bool, str | None]:
    if len(raw_query) > config.max_query_length:
        raise HTTPException(status_code=status.HTTP_414_REQUEST_URI_TOO_LONG, detail="Query string too large.")
    try:
        pairs = parse_qsl(
            raw_query,
            keep_blank_values=True,
            strict_parsing=False,
            max_num_fields=config.max_query_fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid query string.") from exc

    query_api_keys = [value for key, value in pairs if key == "ApiKey"]
    if len(query_api_keys) > 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ApiKey may be provided only once.")

    supplied_api_key = query_api_keys[0] if query_api_keys else None
    if supplied_api_key is not None and len(supplied_api_key) > 512:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
    if header_api_key is not None and len(header_api_key) > 512:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
    if header_api_key is not None:
        if supplied_api_key is not None and not secrets.compare_digest(header_api_key, supplied_api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Conflicting API credentials.")
        supplied_api_key = header_api_key

    priority = False
    if supplied_api_key is not None:
        if not config.api_key or not secrets.compare_digest(supplied_api_key, config.api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
        priority = True

    forwarded_pairs = [(key, value) for key, value in pairs if key != "ApiKey"]
    thread_values = [value for key, value in forwarded_pairs if key == "thread_id"]
    if len(thread_values) > 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="thread_id may be provided only once.")
    thread_id = thread_values[0] if thread_values else None
    if thread_id is not None and (not thread_id.isdigit() or len(thread_id) > 20):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid thread_id.")

    return urlencode(forwarded_pairs, doseq=True), priority, thread_id


def derive_target_context(thread_id: str | None, normalized_content_type: str, body: bytes) -> str:
    if thread_id:
        return f"thread_id:{thread_id}"
    if normalized_content_type in {"application/json", "text/json"}:
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            return "webhook"
        if isinstance(payload, dict):
            thread_name = payload.get("thread_name")
            if isinstance(thread_name, str) and thread_name:
                return f"thread_name:{sha256_text(thread_name)[:24]}"
    return "webhook"


def request_fingerprint(body: bytes, query_string: str, content_type: str) -> str:
    digest = hashlib.sha256()
    digest.update(body)
    digest.update(b"\x00")
    digest.update(query_string.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(normalize_content_type(content_type).encode("utf-8"))
    return digest.hexdigest()


def estimated_storage_bytes(
    body_b64: str,
    query_string: str,
    content_type: str,
    webhook_token: str,
    storage_overhead_bytes: int,
) -> int:
    return len(body_b64) + len(query_string) + len(content_type) + len(webhook_token) + storage_overhead_bytes




async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large.")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Content-Length header.")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large.")
        chunks.append(chunk)
    return b"".join(chunks)


class AppState:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.redis = redis.from_url(
            config.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=config.redis_health_check_interval_seconds,
            socket_connect_timeout=config.redis_socket_connect_timeout_seconds,
            socket_timeout=config.redis_socket_timeout_seconds,
            socket_keepalive=True,
        )
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.http_timeout_seconds, connect=5.0),
            limits=httpx.Limits(
                max_keepalive_connections=config.http_max_keepalive_connections,
                max_connections=config.http_max_connections,
            ),
            follow_redirects=False,
        )
        self.shutdown_event = asyncio.Event()
        self.tasks: list[asyncio.Task[Any]] = []
        self.ingress_slots = asyncio.Semaphore(config.ingress_concurrency)

    @property
    def ready_targets_key(self) -> str:
        return f"{self.config.queue_prefix}:ready:webhooks"

    @property
    def processing_jobs_key(self) -> str:
        return f"{self.config.queue_prefix}:processing:jobs"

    @property
    def processing_meta_key(self) -> str:
        return f"{self.config.queue_prefix}:processing:meta"

    @property

    @property
    def stats_key(self) -> str:
        return f"{self.config.queue_prefix}:stats"

    @property
    def pending_jobs_key(self) -> str:
        return f"{self.config.queue_prefix}:pending:jobs"

    @property
    def pending_bytes_key(self) -> str:
        return f"{self.config.queue_prefix}:pending:bytes"

    @property
    def unique_webhooks_hll_key(self) -> str:
        return f"{self.config.queue_prefix}:unique:webhooks:hll"

    @property
    def legacy_unique_webhooks_key(self) -> str:
        return f"{self.config.queue_prefix}:unique:webhooks"

    @property
    def idempotency_index_key(self) -> str:
        return f"{self.config.queue_prefix}:idempotency:index"

    @property
    def global_backoff_key(self) -> str:
        return f"{self.config.queue_prefix}:discord:global-backoff"

    @property
    def global_dispatch_window_key(self) -> str:
        return f"{self.config.queue_prefix}:discord:global-window"

    @property
    def invalid_request_window_key(self) -> str:
        return f"{self.config.queue_prefix}:discord:invalid-window"

    def webhook_backoff_key(self, webhook_key_value: str) -> str:
        return f"{self.config.queue_prefix}:discord:webhook-backoff:{webhook_key_value}"

    def job_key(self, job_id: str) -> str:
        return f"{self.config.queue_prefix}:job:{job_id}"

    def result_key(self, job_id: str) -> str:
        return f"{self.config.queue_prefix}:result:{job_id}"

    def target_queue_key(self, target_key_value: str) -> str:
        return f"{self.config.queue_prefix}:webhook-queue:{target_key_value}"

    def target_bytes_key(self, target_key_value: str) -> str:
        return f"{self.config.queue_prefix}:pending:target-bytes:{target_key_value}"

    def webhook_pending_key(self, webhook_key_value: str) -> str:
        return f"{self.config.queue_prefix}:pending:webhook-jobs:{webhook_key_value}"

    def webhook_bytes_key(self, webhook_key_value: str) -> str:
        return f"{self.config.queue_prefix}:pending:webhook-bytes:{webhook_key_value}"

    def claim_key(self, job_id: str) -> str:
        return f"{self.config.queue_prefix}:claim:{job_id}"

    def lock_key(self, target_key_value: str) -> str:
        return f"{self.config.queue_prefix}:lock:{target_key_value}"

    def webhook_lock_key(self, webhook_key_value: str) -> str:
        return f"{self.config.queue_prefix}:discord:webhook-lock:{webhook_key_value}"

    def idempotency_key(self, webhook_key_value: str, idempotency_key_value: str) -> str:
        return f"{self.config.queue_prefix}:idempotency:{webhook_key_value}:{sha256_text(idempotency_key_value)}"

    @property
    def global_ingress_rate_limit_key(self) -> str:
        return f"{self.config.queue_prefix}:ratelimit:global:window"

    def rate_limit_key(self, subject_key: str, kind: str) -> str:
        return f"{self.config.queue_prefix}:ratelimit:webhook:{subject_key}:{kind}"


    async def start(self) -> None:
        await self.redis.ping()
        await self.purge_obsolete_storage()
        for index in range(self.config.dispatch_concurrency):
            self.tasks.append(asyncio.create_task(self.worker_loop(index), name=f"worker-{index}"))
        self.tasks.append(asyncio.create_task(self.reclaim_loop(), name="reclaimer"))

    async def stop(self) -> None:
        self.shutdown_event.set()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.http_client.aclose()
        await self.redis.aclose()

    async def purge_obsolete_storage(self) -> None:
        batch: list[str] = []
        async for key in self.redis.scan_iter(
            match=f"{self.config.queue_prefix}:deadletter:*",
            count=1000,
        ):
            batch.append(key)
            if len(batch) >= 500:
                await self.redis.unlink(*batch)
                batch.clear()
        if batch:
            await self.redis.unlink(*batch)
        await self.redis.hdel(self.stats_key, "deadletter", "deadletter_dropped")

    async def wait_for_delivery_result(
        self,
        job_id: str,
        request: Request,
    ) -> tuple[dict[str, str] | None, str]:
        deadline = time.monotonic() + self.config.caller_wait_timeout_seconds
        while True:
            result = await self.redis.hgetall(self.result_key(job_id))
            if result:
                return result, "completed"
            if await request.is_disconnected():
                return None, "disconnected"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "timeout"
            await asyncio.sleep(min(self.config.result_poll_interval_seconds, remaining))

    async def increment_stat(self, field: str, amount: int = 1) -> None:
        try:
            await self.redis.hincrby(self.stats_key, field, amount)
        except RedisError:
            return

    async def set_max_backoff(self, key: str, delay_seconds: float) -> None:
        ttl_ms = max(1, int((delay_seconds + 0.25) * 1000))
        await self.redis.eval(SET_MAX_BACKOFF_LUA, 1, key, str(ttl_ms))

    async def set_global_backoff(self, delay_seconds: float) -> None:
        await self.set_max_backoff(self.global_backoff_key, delay_seconds)

    async def set_webhook_backoff(self, webhook_key_value: str, delay_seconds: float) -> None:
        await self.set_max_backoff(self.webhook_backoff_key(webhook_key_value), delay_seconds)

    async def record_invalid_request(self) -> None:
        try:
            await self.redis.eval(
                RECORD_INVALID_REQUEST_LUA,
                3,
                self.invalid_request_window_key,
                self.global_backoff_key,
                self.stats_key,
                str(self.config.discord_invalid_request_limit),
                str(self.config.discord_invalid_request_window_seconds * 1000),
            )
        except RedisError:
            return

    async def sleep_if_global_backoff(self) -> bool:
        ttl_ms = await self.redis.pttl(self.global_backoff_key)
        if ttl_ms and ttl_ms > 0:
            await asyncio.sleep(min(ttl_ms / 1000.0, self.config.poll_interval_seconds))
            return True
        return False

    async def check_rate_limit(self, subject_key: str) -> dict[str, Any]:
        result = await self.redis.eval(
            RATE_LIMIT_LUA,
            4,
            self.rate_limit_key(subject_key, "window"),
            self.rate_limit_key(subject_key, "violations"),
            self.rate_limit_key(subject_key, "block"),
            self.global_ingress_rate_limit_key,
            str(self.config.webhook_rate_limit_requests),
            str(self.config.webhook_rate_limit_window_seconds),
            str(self.config.rate_limit_violation_ttl_seconds),
            str(self.config.webhook_abuse_block_after),
            str(self.config.webhook_abuse_base_block_seconds),
            str(self.config.webhook_abuse_max_block_seconds),
            str(self.config.webhook_abuse_burst_multiplier),
            str(self.config.global_ingress_rate_limit_requests),
            str(self.config.global_ingress_rate_limit_window_seconds),
        )
        allowed, retry_after, blocked, count, limit = result
        return {
            "allowed": int(allowed) == 1,
            "retry_after": int(retry_after),
            "blocked": int(blocked) == 1,
            "count": int(count),
            "limit": int(limit),
        }

    async def preflight_admission(
        self,
        webhook_key_value: str,
        target_key_value: str,
        priority: bool,
        estimated_request_bytes: int,
        check_target: bool = True,
    ) -> str | None:
        if priority:
            pending_jobs, pending_bytes = await self.redis.mget(self.pending_jobs_key, self.pending_bytes_key)
            if int(pending_jobs or 0) + 1 > self.config.absolute_queue_limit:
                return "absolute_count_overloaded"
            if int(pending_bytes or 0) + estimated_request_bytes > self.config.absolute_queue_bytes_limit:
                return "absolute_bytes_overloaded"
            return None

        pipe = self.redis.pipeline(transaction=False)
        pipe.llen(self.target_queue_key(target_key_value))
        pipe.get(self.webhook_pending_key(webhook_key_value))
        pipe.get(self.pending_jobs_key)
        pipe.get(self.target_bytes_key(target_key_value))
        pipe.get(self.webhook_bytes_key(webhook_key_value))
        pipe.get(self.pending_bytes_key)
        target_count, webhook_count, global_count, target_bytes, webhook_bytes, global_bytes = await pipe.execute()

        if check_target and int(target_count or 0) >= self.config.target_queue_limit:
            return "target_count_overloaded"
        if int(webhook_count or 0) >= self.config.webhook_queue_limit:
            return "webhook_count_overloaded"
        if int(global_count or 0) >= self.config.global_queue_limit:
            return "global_count_overloaded"
        if check_target and int(target_bytes or 0) + estimated_request_bytes > self.config.target_queue_bytes_limit:
            return "target_bytes_overloaded"
        if int(webhook_bytes or 0) + estimated_request_bytes > self.config.webhook_queue_bytes_limit:
            return "webhook_bytes_overloaded"
        if int(global_bytes or 0) + estimated_request_bytes > self.config.global_queue_bytes_limit:
            return "global_bytes_overloaded"
        return None

    async def claim_next_job(self) -> tuple[str, str, str, str, str] | None:
        claim_token = uuid.uuid4().hex
        result = await self.redis.eval(
            CLAIM_NEXT_JOB_LUA,
            7,
            self.ready_targets_key,
            self.processing_jobs_key,
            self.processing_meta_key,
            self.global_backoff_key,
            self.global_dispatch_window_key,
            self.pending_jobs_key,
            self.pending_bytes_key,
            str(now_ms()),
            str(self.config.queue_scan_limit),
            self.instance_id,
            str(int(self.config.claim_visibility_seconds * 1000)),
            f"{self.config.queue_prefix}:webhook-queue:",
            f"{self.config.queue_prefix}:job:",
            f"{self.config.queue_prefix}:claim:",
            f"{self.config.queue_prefix}:lock:",
            f"{self.config.queue_prefix}:discord:webhook-lock:",
            f"{self.config.queue_prefix}:discord:webhook-backoff:",
            f"{self.config.queue_prefix}:pending:webhook-jobs:",
            f"{self.config.queue_prefix}:pending:webhook-bytes:",
            f"{self.config.queue_prefix}:pending:target-bytes:",
            str(self.config.stale_cleanup_limit),
            str(self.config.discord_global_requests_per_second),
            claim_token,
            str(max(25, int(self.config.poll_interval_seconds * 1000))),
        )
        if not result:
            return None
        job_id, target_key_value, queue_entry, webhook_key_value, returned_token, _ = result
        return str(job_id), str(target_key_value), str(queue_entry), str(webhook_key_value), str(returned_token)

    async def finalize_job(
        self,
        job_id: str,
        target_key_value: str,
        queue_entry: str,
        webhook_key_value: str,
        claim_token: str,
        delete_job: bool = True,
        result: dict[str, str] | None = None,
        idempotency_redis_key: str = "",
    ) -> str:
        result_values = result or {}
        result_key_value = self.result_key(job_id)
        idempotency_key_value = idempotency_redis_key or result_key_value
        response = await self.redis.eval(
            FINALIZE_JOB_LUA,
            15,
            self.ready_targets_key,
            self.processing_jobs_key,
            self.processing_meta_key,
            self.pending_jobs_key,
            self.pending_bytes_key,
            self.job_key(job_id),
            self.target_queue_key(target_key_value),
            self.claim_key(job_id),
            self.lock_key(target_key_value),
            self.webhook_pending_key(webhook_key_value),
            self.webhook_bytes_key(webhook_key_value),
            self.target_bytes_key(target_key_value),
            self.webhook_lock_key(webhook_key_value),
            result_key_value,
            idempotency_key_value,
            job_id,
            target_key_value,
            queue_entry,
            webhook_key_value,
            claim_token,
            "1" if delete_job else "0",
            f"{self.config.queue_prefix}:job:",
            f"{self.config.queue_prefix}:webhook-queue:",
            f"{self.config.queue_prefix}:claim:",
            f"{self.config.queue_prefix}:lock:",
            f"{self.config.queue_prefix}:pending:webhook-jobs:",
            f"{self.config.queue_prefix}:pending:webhook-bytes:",
            f"{self.config.queue_prefix}:pending:target-bytes:",
            str(self.config.stale_cleanup_limit),
            str(now_ms()),
            "1" if result is not None else "0",
            str(self.config.result_ttl_seconds),
            result_values.get("status_code", ""),
            result_values.get("body_b64", ""),
            result_values.get("content_type", ""),
            result_values.get("headers_json", "{}"),
            result_values.get("attempts", "1"),
            result_values.get("result_kind", "unknown"),
            result_values.get("result_message", ""),
            result_values.get("request_id", ""),
            "1" if idempotency_redis_key else "0",
        )
        return str(response[0]) if response else "unknown"

    async def reschedule_job(
        self,
        job_id: str,
        target_key_value: str,
        queue_entry: str,
        webhook_key_value: str,
        claim_token: str,
        next_available_at_ms: int,
        attempts: int,
        last_error: str,
        last_status: str,
    ) -> str:
        result = await self.redis.eval(
            RESCHEDULE_JOB_LUA,
            7,
            self.ready_targets_key,
            self.processing_jobs_key,
            self.processing_meta_key,
            self.job_key(job_id),
            self.claim_key(job_id),
            self.lock_key(target_key_value),
            self.webhook_lock_key(webhook_key_value),
            job_id,
            target_key_value,
            str(next_available_at_ms),
            str(attempts),
            last_error,
            last_status,
            str(self.config.job_ttl_seconds),
            claim_token,
        )
        state = str(result[0]) if result else "unknown"
        if state == "missing":
            return await self.finalize_job(
                job_id,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                delete_job=True,
            )
        return state

    async def enqueue_job(
        self,
        webhook_id: str,
        webhook_token: str,
        webhook_key_value: str,
        target_key_value: str,
        target_context: str,
        query_string: str,
        body: bytes,
        content_type: str,
        priority: bool,
        idempotency_key_value: str | None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        request_id = uuid.uuid4().hex
        created_at_ms = now_ms()
        body_sha256 = sha256_bytes(body)
        request_sha256 = request_fingerprint(body, query_string, content_type)
        body_b64 = encode_body(body)
        storage_bytes = estimated_storage_bytes(
            body_b64,
            query_string,
            content_type,
            webhook_token,
            self.config.storage_overhead_bytes,
        )
        idem_key_name = self.idempotency_key(webhook_key_value, idempotency_key_value) if idempotency_key_value else ""

        result = await self.redis.eval(
            ENQUEUE_JOB_LUA,
            12,
            self.job_key(job_id),
            self.target_queue_key(target_key_value),
            self.ready_targets_key,
            self.pending_jobs_key,
            self.pending_bytes_key,
            self.webhook_pending_key(webhook_key_value),
            self.webhook_bytes_key(webhook_key_value),
            self.target_bytes_key(target_key_value),
            self.unique_webhooks_hll_key,
            self.stats_key,
            idem_key_name,
            self.idempotency_index_key,
            job_id,
            request_id,
            webhook_id,
            webhook_token,
            webhook_key_value,
            target_key_value,
            target_context,
            query_string,
            body_b64,
            content_type,
            str(created_at_ms),
            body_sha256,
            request_sha256,
            idempotency_key_value or "",
            str(self.config.job_ttl_seconds),
            str(self.config.idempotency_ttl_seconds),
            str(storage_bytes),
            "1" if priority else "0",
            str(self.config.target_queue_limit),
            str(self.config.webhook_queue_limit),
            str(self.config.global_queue_limit),
            str(self.config.target_queue_bytes_limit),
            str(self.config.webhook_queue_bytes_limit),
            str(self.config.global_queue_bytes_limit),
            str(self.config.absolute_queue_limit),
            str(self.config.absolute_queue_bytes_limit),
            str(self.config.idempotency_max_entries),
            str(self.config.idempotency_cleanup_limit),
        )

        result_status = str(result[0])
        result_request_id = str(result[1])
        result_job_id = str(result[2])

        if result_status == "conflict":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conflicting request for the same idempotency key.",
            )

        if result_status.endswith("_overloaded"):
            return {
                "status": result_status,
                "request_id": result_request_id,
                "job_id": result_job_id,
                "duplicate": False,
                "storage_bytes": storage_bytes,
            }

        return {
            "status": result_status,
            "request_id": result_request_id,
            "duplicate": result_status == "duplicate",
            "job_id": result_job_id,
            "storage_bytes": storage_bytes,
        }


    async def worker_loop(self, _worker_index: int) -> None:
        while not self.shutdown_event.is_set():
            try:
                if await self.sleep_if_global_backoff():
                    continue

                claim = await self.claim_next_job()
                if claim is None:
                    await asyncio.sleep(self.config.poll_interval_seconds)
                    continue

                job_id, target_key_value, queue_entry, webhook_key_value, claim_token = claim
                job = await self.redis.hgetall(self.job_key(job_id))
                if not job:
                    await self.finalize_job(
                        job_id,
                        target_key_value,
                        queue_entry,
                        webhook_key_value,
                        claim_token,
                        delete_job=True,
                    )
                    continue

                await self.process_job(
                    job,
                    target_key_value,
                    queue_entry,
                    webhook_key_value,
                    claim_token,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(self.config.poll_interval_seconds)

    async def process_job(
        self,
        job: dict[str, str],
        target_key_value: str,
        queue_entry: str,
        webhook_key_value: str,
        claim_token: str,
    ) -> None:
        job_id = job["job_id"]
        request_id = job.get("request_id", "")
        idempotency_redis_key = job.get("idempotency_redis_key", "")
        attempts = int(job.get("attempts", "0"))
        attempt_number = attempts + 1
        url = build_discord_url(job["webhook_id"], job["webhook_token"], job.get("query_string", ""))

        try:
            body = decode_body(job["body_b64"])
        except (ValueError, TypeError):
            result = proxy_delivery_result(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "stored_payload_corrupt",
                "The queued payload could not be decoded safely.",
                attempt_number,
                request_id,
            )
            await self.finalize_job(
                job_id,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                result=result,
                idempotency_redis_key=idempotency_redis_key,
            )
            await self.increment_stat("discarded")
            return

        headers = {
            "Content-Type": job.get("content_type", "application/json"),
            "User-Agent": "discord-webhook-proxy/5.0",
        }

        try:
            response = await self.http_client.post(url, content=body, headers=headers)
        except httpx.TimeoutException:
            final_result = proxy_delivery_result(
                status.HTTP_504_GATEWAY_TIMEOUT,
                "discord_timeout",
                "Discord did not respond before the configured request timeout.",
                attempt_number,
                request_id,
            )
            await self.handle_retry(
                job,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                attempt_number,
                "upstream_timeout",
                "",
                retry_delay_seconds(attempt_number, self.config),
                "Discord request timed out.",
                final_result,
            )
            return
        except httpx.RequestError:
            final_result = proxy_delivery_result(
                status.HTTP_502_BAD_GATEWAY,
                "discord_network_failure",
                "The proxy could not complete the network request to Discord.",
                attempt_number,
                request_id,
            )
            await self.handle_retry(
                job,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                attempt_number,
                "network_error",
                "",
                retry_delay_seconds(attempt_number, self.config),
                "Discord network request failed.",
                final_result,
            )
            return

        status_code = response.status_code
        final_result = upstream_delivery_result(
            response,
            attempt_number,
            request_id,
            self.config.max_upstream_response_bytes,
        )

        if status_code in {401, 403, 429}:
            await self.record_invalid_request()

        reset_after = get_bucket_reset_after_seconds(response)
        if reset_after is not None and reset_after > 0:
            await self.set_webhook_backoff(webhook_key_value, reset_after)

        if int(final_result["status_code"]) != status_code:
            await self.finalize_job(
                job_id,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                result=final_result,
                idempotency_redis_key=idempotency_redis_key,
            )
            await self.increment_stat("discarded")
            return

        if 200 <= status_code < 300:
            await self.finalize_job(
                job_id,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                result=final_result,
                idempotency_redis_key=idempotency_redis_key,
            )
            await self.increment_stat("sent")
            return

        if status_code == 429:
            retry_after = get_retry_after_seconds(response)
            if is_global_rate_limited(response):
                await self.set_global_backoff(retry_after)
            else:
                await self.set_webhook_backoff(webhook_key_value, retry_after)
            await self.handle_retry(
                job,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                attempt_number,
                "rate_limited",
                str(status_code),
                retry_delay_seconds(attempt_number, self.config, retry_after),
                final_result.get("result_message", "Discord rate limited the request."),
                final_result,
            )
            return

        if status_code >= 500 or status_code in {408, 409, 425}:
            await self.handle_retry(
                job,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                attempt_number,
                "upstream_error",
                str(status_code),
                retry_delay_seconds(attempt_number, self.config),
                final_result.get("result_message", f"Discord returned HTTP {status_code}."),
                final_result,
            )
            return

        await self.finalize_job(
            job_id,
            target_key_value,
            queue_entry,
            webhook_key_value,
            claim_token,
            result=final_result,
            idempotency_redis_key=idempotency_redis_key,
        )
        await self.increment_stat("discarded")

    async def handle_retry(
        self,
        job: dict[str, str],
        target_key_value: str,
        queue_entry: str,
        webhook_key_value: str,
        claim_token: str,
        attempts: int,
        reason: str,
        status_value: str,
        delay_seconds: float,
        last_error: str,
        final_result: dict[str, str],
    ) -> None:
        job_id = job["job_id"]
        if attempts > self.config.max_retries:
            await self.finalize_job(
                job_id,
                target_key_value,
                queue_entry,
                webhook_key_value,
                claim_token,
                result=final_result,
                idempotency_redis_key=job.get("idempotency_redis_key", ""),
            )
            await self.increment_stat("discarded")
            return

        next_available_at = now_ms() + int(delay_seconds * 1000)
        state = await self.reschedule_job(
            job_id=job_id,
            target_key_value=target_key_value,
            queue_entry=queue_entry,
            webhook_key_value=webhook_key_value,
            claim_token=claim_token,
            next_available_at_ms=next_available_at,
            attempts=attempts,
            last_error=truncate_text(last_error, 500),
            last_status=status_value,
        )
        if state == "rescheduled":
            await self.increment_stat("retried")

    async def reclaim_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(self.config.reclaim_interval_seconds)
                await self.reclaim_expired_jobs()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    async def reclaim_expired_jobs(self) -> None:
        expired_ids = await self.redis.zrangebyscore(
            self.processing_jobs_key,
            min="-inf",
            max=now_ms(),
            start=0,
            num=self.config.queue_scan_limit,
        )
        if not expired_ids:
            return

        reclaimed = 0
        for job_id in expired_ids:
            result = await self.redis.eval(
                RECLAIM_JOB_LUA,
                7,
                self.ready_targets_key,
                self.processing_jobs_key,
                self.processing_meta_key,
                self.pending_jobs_key,
                self.pending_bytes_key,
                self.job_key(job_id),
                self.claim_key(job_id),
                job_id,
                str(now_ms()),
                str(self.config.job_ttl_seconds),
                f"{self.config.queue_prefix}:webhook-queue:",
                f"{self.config.queue_prefix}:job:",
                f"{self.config.queue_prefix}:lock:",
                f"{self.config.queue_prefix}:pending:webhook-jobs:",
                f"{self.config.queue_prefix}:pending:webhook-bytes:",
                f"{self.config.queue_prefix}:pending:target-bytes:",
                f"{self.config.queue_prefix}:discord:webhook-lock:",
                str(self.config.stale_cleanup_limit),
            )
            state = str(result[0]) if result else "unknown"
            if state == "reclaimed":
                reclaimed += 1

        if reclaimed:
            await self.increment_stat("reclaimed", reclaimed)


def get_state(request: Request) -> AppState:
    state = getattr(request.app.state, "state", None)
    if not state:
        raise RuntimeError("Application state is not initialized.")
    return state


@asynccontextmanager
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    config = Config()
    state = AppState(config)
    app_instance.state.state = state
    await state.start()
    try:
        yield
    finally:
        await state.stop()


app = FastAPI(
    title="Discord Webhook Proxy",
    description="A queue-bounded, rate-limit-aware relay that returns terminal Discord responses.",
    version="5.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response: Response
    if request.method == "POST":
        match = WEBHOOK_PATH_RE.fullmatch(request.url.path)
        state = getattr(request.app.state, "state", None)
        if (
            match
            and state is not None
            and webhook_key(match.group(1), match.group(2)) in state.config.blacklisted_webhook_keys
        ):
            response = blacklisted_webhook_response()
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.get("/", response_class=HTMLResponse)
async def serve_frontend() -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    csp = (
        "default-src 'self'; "
        "base-uri 'none'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "img-src 'self' data:; "
        f"style-src 'self' 'nonce-{nonce}'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "connect-src 'self'; "
        "form-action 'none'; "
        "upgrade-insecure-requests"
    )
    return HTMLResponse(
        content=INDEX_HTML_TEMPLATE.replace("__NONCE__", nonce),
        headers={"Content-Security-Policy": csp, "Cache-Control": "no-store"},
    )


@app.get("/favicon.png")
async def favicon() -> Response:
    if FAVICON_PATH.exists():
        return Response(content=FAVICON_PATH.read_bytes(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/og-image.png")
async def og_image() -> Response:
    if FAVICON_PATH.exists():
        return Response(content=FAVICON_PATH.read_bytes(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/stats")
@app.get("/api/stats")
async def api_stats(request: Request) -> JSONResponse:
    state = get_state(request)
    try:
        pipe = state.redis.pipeline(transaction=False)
        pipe.hgetall(state.stats_key)
        pipe.pfcount(state.unique_webhooks_hll_key)
        pipe.scard(state.legacy_unique_webhooks_key)
        pipe.get(state.pending_jobs_key)
        pipe.get(state.pending_bytes_key)
        pipe.zcard(state.ready_targets_key)
        pipe.zcard(state.processing_jobs_key)
        (
            stats_raw,
            hll_webhooks,
            legacy_webhooks,
            pending_jobs,
            pending_bytes,
            ready_targets,
            processing_jobs,
        ) = await pipe.execute()
        stats = integer_dict(stats_raw)
        requests_served = stats.get("accepted", 0) + stats.get("duplicates", 0)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            headers={"Cache-Control": "no-store"},
            content={
                "unique_webhooks": max(int(hll_webhooks or 0), int(legacy_webhooks or 0)),
                "requests_served": requests_served,
                "accepted": stats.get("accepted", 0),
                "duplicates": stats.get("duplicates", 0),
                "sent": stats.get("sent", 0),
                "retried": stats.get("retried", 0),
                "discarded": stats.get("discarded", 0),
                "rejected": stats.get("rejected", 0),
                "blocked": stats.get("blocked", 0),
                "rate_limited": stats.get("rate_limited", 0),
                "invalid_requests": stats.get("invalid_requests", 0),
                "reclaimed": stats.get("reclaimed", 0),
                "ingress_rejected": stats.get("ingress_rejected", 0),
                "pending_jobs": max(int(pending_jobs or 0), 0),
                "pending_bytes": max(int(pending_bytes or 0), 0),
                "ready_targets": int(ready_targets or 0),
                "processing_jobs": int(processing_jobs or 0),
            },
        )
    except RedisError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "Stats are temporarily unavailable.",
                "message": "Stats are temporarily unavailable.",
                "code": "stats_unavailable",
            },
        )


@app.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    state = get_state(request)
    try:
        await state.redis.ping()
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})
    except RedisError:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "degraded"})


@app.get("/readyz")
async def readyz(request: Request) -> Response:
    state = get_state(request)
    try:
        await state.redis.ping()
    except RedisError:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/webhooks/{full_path:path}", response_class=RedirectResponse, include_in_schema=False)
async def redirect_webhook_get(full_path: str) -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


async def reject_request(
    state: AppState,
    status_code: int,
    error: str,
    stat: str,
    retry_after: int | None = None,
    code: str = "proxy_request_rejected",
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    await state.increment_stat(stat)
    headers = {"Retry-After": str(max(1, retry_after))} if retry_after is not None else None
    content: dict[str, Any] = {
        "error": error,
        "message": error,
        "code": code,
    }
    if retry_after is not None:
        content["retry_after"] = max(1, retry_after)
    if details:
        content.update(details)
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def blacklisted_webhook_response() -> JSONResponse:
    message = "This webhook is blocked from using the proxy."
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error": message,
            "message": message,
            "code": "blacklisted_webhook",
        },
    )


def overload_message(reason: str) -> str:
    if reason.startswith("global_") or reason.startswith("absolute_"):
        return "Global queue capacity was exceeded."
    if reason.startswith("target_"):
        return "The target-specific webhook queue capacity was exceeded."
    return "The webhook queue capacity was exceeded."


async def admit_webhook_request(
    request: Request,
    state: AppState,
    webhook_id: str,
    webhook_token: str,
    webhook_key_value: str,
) -> dict[str, Any] | Response:
    try:
        await asyncio.wait_for(
            state.ingress_slots.acquire(),
            timeout=state.config.ingress_wait_seconds,
        )
    except TimeoutError:
        await state.increment_stat("ingress_rejected")
        message = "The proxy has no free request-admission slot."
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "1"},
            content={
                "error": message,
                "message": message,
                "code": "proxy_admission_capacity_reached",
                "retry_after": 1,
            },
        )

    try:
        api_key_headers = request.headers.getlist("x-api-key")
        if len(api_key_headers) > 1:
            return await reject_request(
                state,
                status.HTTP_400_BAD_REQUEST,
                "X-Api-Key may be provided only once.",
                "rejected",
                code="duplicate_api_key_header",
            )

        try:
            query_string, priority, thread_id = sanitize_query_string(
                request.url.query,
                state.config,
                api_key_headers[0] if api_key_headers else None,
            )
        except HTTPException as exc:
            return await reject_request(
                state,
                exc.status_code,
                str(exc.detail),
                "rejected",
                code="invalid_query_or_api_key",
            )

        idempotency_headers = (
            request.headers.getlist("x-idempotency-key")
            + request.headers.getlist("idempotency-key")
        )
        if len(idempotency_headers) > 1:
            return await reject_request(
                state,
                status.HTTP_400_BAD_REQUEST,
                "Idempotency key may be provided only once.",
                "rejected",
                code="duplicate_idempotency_key",
            )
        idempotency_key_value = idempotency_headers[0] if idempotency_headers else None
        if idempotency_key_value and len(idempotency_key_value) > state.config.max_idempotency_key_length:
            return await reject_request(
                state,
                status.HTTP_400_BAD_REQUEST,
                "Idempotency key too large.",
                "rejected",
                code="idempotency_key_too_large",
            )

        try:
            rate_limit = await state.check_rate_limit(webhook_key_value)
        except RedisError:
            return await reject_request(
                state,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Queue storage is temporarily unavailable.",
                "rejected",
                1,
                code="queue_storage_unavailable",
            )
        if not rate_limit["allowed"]:
            blocked = rate_limit["blocked"]
            await state.increment_stat("blocked" if blocked else "rate_limited")
            retry_after = max(1, rate_limit["retry_after"])
            message = (
                "This webhook is temporarily blocked after repeated proxy rate-limit violations."
                if blocked
                else "This webhook exceeded the proxy ingress rate limit."
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": message,
                    "message": message,
                    "code": "proxy_webhook_temporarily_blocked" if blocked else "proxy_webhook_rate_limited",
                    "retry_after": retry_after,
                    "observed_requests": rate_limit["count"],
                    "request_limit": rate_limit["limit"],
                },
            )

        normalized_content_type = normalize_content_type(request.headers.get("content-type", ""))
        preliminary_context = f"thread_id:{thread_id}" if thread_id else "webhook"
        preliminary_target_key = target_key(webhook_key_value, preliminary_context)
        content_length = request.headers.get("content-length")
        estimated_request_bytes = state.config.storage_overhead_bytes
        if content_length:
            try:
                estimated_request_bytes += max(0, int(content_length) * 4 // 3)
            except ValueError:
                return await reject_request(
                    state,
                    status.HTTP_400_BAD_REQUEST,
                    "Invalid Content-Length header.",
                    "rejected",
                    code="invalid_content_length",
                )

        if not idempotency_key_value:
            try:
                preflight_reason = await state.preflight_admission(
                    webhook_key_value,
                    preliminary_target_key,
                    priority,
                    estimated_request_bytes,
                    check_target=thread_id is not None or normalized_content_type not in {"application/json", "text/json"},
                )
            except RedisError:
                return await reject_request(
                    state,
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Queue storage is temporarily unavailable.",
                    "rejected",
                    1,
                    code="queue_storage_unavailable",
                )
            if preflight_reason:
                retry_after = state.config.overload_retry_after_seconds
                message = overload_message(preflight_reason)
                return await reject_request(
                    state,
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    message,
                    "rejected",
                    retry_after,
                    code=preflight_reason,
                    details={"capacity_scope": preflight_reason},
                )

        try:
            body = await read_limited_body(request, state.config.max_body_bytes)
        except HTTPException as exc:
            return await reject_request(
                state,
                exc.status_code,
                str(exc.detail),
                "rejected",
                code="invalid_request_body",
            )

        if not body:
            return await reject_request(
                state,
                status.HTTP_400_BAD_REQUEST,
                "Empty payload rejected.",
                "rejected",
                code="empty_payload",
            )

        try:
            content_type = validate_content_type(
                request.headers.get("content-type", ""),
                state.config.max_content_type_length,
            )
        except HTTPException as exc:
            return await reject_request(
                state,
                exc.status_code,
                str(exc.detail),
                "rejected",
                code="invalid_content_type",
            )

        normalized_content_type = normalize_content_type(content_type)
        if normalized_content_type in {"application/json", "text/json"} or (
            not normalized_content_type and looks_like_json(body)
        ):
            try:
                json.loads(body)
            except (ValueError, TypeError):
                return await reject_request(
                    state,
                    status.HTTP_400_BAD_REQUEST,
                    "Malformed JSON payload rejected.",
                    "rejected",
                    code="malformed_json",
                )
            if not content_type:
                content_type = "application/json"

        if not content_type:
            content_type = "application/octet-stream"

        target_context = derive_target_context(
            thread_id,
            normalize_content_type(content_type),
            body,
        )
        target_key_value = target_key(webhook_key_value, target_context)

        try:
            enqueue_result = await state.enqueue_job(
                webhook_id=webhook_id,
                webhook_token=webhook_token,
                webhook_key_value=webhook_key_value,
                target_key_value=target_key_value,
                target_context=target_context,
                query_string=query_string,
                body=body,
                content_type=content_type,
                priority=priority,
                idempotency_key_value=idempotency_key_value,
            )
        except HTTPException as exc:
            return await reject_request(
                state,
                exc.status_code,
                str(exc.detail),
                "rejected",
                code="idempotency_conflict",
            )
        except RedisError:
            return await reject_request(
                state,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Queue storage is temporarily unavailable.",
                "rejected",
                1,
                code="queue_storage_unavailable",
            )

        if enqueue_result["status"].endswith("_overloaded"):
            retry_after = state.config.overload_retry_after_seconds
            message = overload_message(enqueue_result["status"])
            return await reject_request(
                state,
                status.HTTP_429_TOO_MANY_REQUESTS,
                message,
                "rejected",
                retry_after,
                code=enqueue_result["status"],
                details={"capacity_scope": enqueue_result["status"]},
            )

        return {
            "enqueue_result": enqueue_result,
            "priority": priority,
            "target_context": target_context,
        }
    finally:
        state.ingress_slots.release()


@app.post("/api/webhooks/{webhook_id}/{webhook_token}")
async def proxy_webhook(
    request: Request,
    webhook_id: str = FastAPIPath(..., pattern=r"^\d+$", max_length=20),
    webhook_token: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_-]+$", max_length=256),
) -> Response:
    state = get_state(request)
    webhook_key_value = webhook_key(webhook_id, webhook_token)

    if webhook_key_value in state.config.blacklisted_webhook_keys:
        return blacklisted_webhook_response()

    admission = await admit_webhook_request(
        request,
        state,
        webhook_id,
        webhook_token,
        webhook_key_value,
    )
    if isinstance(admission, Response):
        return admission

    enqueue_result = admission["enqueue_result"]
    try:
        result, wait_state = await state.wait_for_delivery_result(
            enqueue_result["job_id"],
            request,
        )
    except RedisError:
        message = "The proxy lost access to the delivery result store."
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "1"},
            content={
                "error": message,
                "message": message,
                "code": "delivery_result_store_unavailable",
                "request_id": enqueue_result["request_id"],
                "retry_after": 1,
            },
        )

    if wait_state == "completed" and result is not None:
        return delivery_response(result, enqueue_result["request_id"])

    if wait_state == "disconnected":
        return Response(status_code=499)

    message = "Discord delivery did not reach a terminal result before the proxy response deadline."
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content={
            "error": message,
            "message": message,
            "code": "delivery_result_timeout",
            "request_id": enqueue_result["request_id"],
            "job_id": enqueue_result["job_id"],
            "duplicate": enqueue_result["duplicate"],
        },
    )


@app.get("/{full_path:path}", response_class=RedirectResponse, include_in_schema=False)
async def redirect_unknown_get(full_path: str) -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
