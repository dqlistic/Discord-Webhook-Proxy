import asyncio
import base64
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Path as FastAPIPath, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

WEBHOOK_PATH_RE = re.compile(r"^/api/webhooks/(\d+)/([A-Za-z0-9_-]+)$")
FAVICON_PATH = Path(__file__).with_name("favicon.png")

INDEX_HTML_TEMPLATE = """
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
local global_backoff_key = KEYS[3]
local pending_jobs_key = KEYS[4]
local now_ms = tonumber(ARGV[1])
local scan_limit = tonumber(ARGV[2])
local consumer = ARGV[3]
local visibility_ms = tonumber(ARGV[4])
local queue_prefix = ARGV[5]
local job_prefix = ARGV[6]
local claim_prefix = ARGV[7]
local lock_prefix = ARGV[8]

if redis.call('EXISTS', global_backoff_key) == 1 then
    return {}
end

local function decrement_pending()
    local pending = redis.call('DECR', pending_jobs_key)
    if pending < 0 then
        redis.call('SET', pending_jobs_key, '0')
    end
end

local function promote_head(webhook_key)
    local queue_key = queue_prefix .. webhook_key
    while true do
        local job_id = redis.call('LINDEX', queue_key, 0)
        if not job_id then
            redis.call('ZREM', ready_key, webhook_key)
            redis.call('DEL', queue_key)
            return nil
        end

        local job_key = job_prefix .. job_id
        if redis.call('EXISTS', job_key) == 0 then
            redis.call('LPOP', queue_key)
            decrement_pending()
        else
            local available_at = redis.call('HGET', job_key, 'available_at_ms')
            if available_at then
                redis.call('ZADD', ready_key, tonumber(available_at), webhook_key)
                return job_id
            end
            redis.call('LPOP', queue_key)
            decrement_pending()
        end
    end
end

local due_webhooks = redis.call('ZRANGEBYSCORE', ready_key, '-inf', now_ms, 'LIMIT', 0, scan_limit)

for _, webhook_key in ipairs(due_webhooks) do
    local job_id = promote_head(webhook_key)
    if job_id then
        local job_key = job_prefix .. job_id
        local available_at = tonumber(redis.call('HGET', job_key, 'available_at_ms') or '0')
        if available_at <= now_ms then
            local lock_key = lock_prefix .. webhook_key
            local claim_key = claim_prefix .. job_id
            if redis.call('SET', lock_key, job_id, 'NX', 'PX', visibility_ms) then
                redis.call('SET', claim_key, consumer, 'PX', visibility_ms)
                redis.call('ZADD', processing_key, now_ms + visibility_ms, job_id)
                redis.call('ZREM', ready_key, webhook_key)
                return {job_id, webhook_key}
            end
        end
    end
end

return {}
"""

FINALIZE_JOB_LUA = """
local ready_key = KEYS[1]
local processing_key = KEYS[2]
local pending_jobs_key = KEYS[3]
local job_id = ARGV[1]
local webhook_key = ARGV[2]
local queue_prefix = ARGV[3]
local job_prefix = ARGV[4]
local claim_prefix = ARGV[5]
local lock_prefix = ARGV[6]
local delete_job = ARGV[7]
local queue_key = queue_prefix .. webhook_key
local job_key = job_prefix .. job_id
local claim_key = claim_prefix .. job_id
local lock_key = lock_prefix .. webhook_key

local function decrement_pending()
    local pending = redis.call('DECR', pending_jobs_key)
    if pending < 0 then
        redis.call('SET', pending_jobs_key, '0')
    end
end

local queue_removed = 0
local head = redis.call('LINDEX', queue_key, 0)
if head == job_id then
    redis.call('LPOP', queue_key)
    queue_removed = 1
else
    queue_removed = redis.call('LREM', queue_key, 1, job_id)
end

redis.call('ZREM', processing_key, job_id)
redis.call('DEL', claim_key)

if redis.call('GET', lock_key) == job_id then
    redis.call('DEL', lock_key)
end

if delete_job == '1' then
    if redis.call('EXISTS', job_key) == 1 then
        redis.call('DEL', job_key)
        decrement_pending()
    elseif queue_removed > 0 then
        decrement_pending()
    end
end

while true do
    local next_job_id = redis.call('LINDEX', queue_key, 0)
    if not next_job_id then
        redis.call('ZREM', ready_key, webhook_key)
        redis.call('DEL', queue_key)
        return ''
    end

    local next_job_key = job_prefix .. next_job_id
    if redis.call('EXISTS', next_job_key) == 0 then
        redis.call('LPOP', queue_key)
        decrement_pending()
    else
        local next_available_at = redis.call('HGET', next_job_key, 'available_at_ms')
        if next_available_at then
            redis.call('ZADD', ready_key, tonumber(next_available_at), webhook_key)
            return next_job_id
        end
        redis.call('LPOP', queue_key)
        decrement_pending()
    end
end
"""

RESCHEDULE_JOB_LUA = """
local ready_key = KEYS[1]
local processing_key = KEYS[2]
local job_id = ARGV[1]
local webhook_key = ARGV[2]
local next_available_at = tonumber(ARGV[3])
local attempts = ARGV[4]
local last_error = ARGV[5]
local last_status = ARGV[6]
local job_ttl = tonumber(ARGV[7])
local queue_prefix = ARGV[8]
local job_prefix = ARGV[9]
local claim_prefix = ARGV[10]
local lock_prefix = ARGV[11]
local job_key = job_prefix .. job_id
local claim_key = claim_prefix .. job_id
local lock_key = lock_prefix .. webhook_key

if redis.call('EXISTS', job_key) == 1 then
    redis.call('HSET', job_key, 'attempts', attempts, 'available_at_ms', tostring(next_available_at), 'last_error', last_error, 'last_status', last_status)
    redis.call('EXPIRE', job_key, job_ttl)
end

redis.call('ZREM', processing_key, job_id)
redis.call('DEL', claim_key)

if redis.call('GET', lock_key) == job_id then
    redis.call('DEL', lock_key)
end

redis.call('ZADD', ready_key, next_available_at, webhook_key)
redis.call('EXPIRE', queue_prefix .. webhook_key, job_ttl)

return 1
"""

RATE_LIMIT_LUA = """
local window_key = KEYS[1]
local violations_key = KEYS[2]
local block_key = KEYS[3]
local limit = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local violation_ttl = tonumber(ARGV[3])
local block_after = tonumber(ARGV[4])
local base_block_seconds = tonumber(ARGV[5])
local max_block_seconds = tonumber(ARGV[6])
local burst_multiplier = tonumber(ARGV[7])

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
if violations == 1 then
    redis.call('EXPIRE', violations_key, violation_ttl)
else
    redis.call('EXPIRE', violations_key, violation_ttl)
end

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
local pending_key = KEYS[4]
local unique_key = KEYS[5]
local stats_key = KEYS[6]
local idem_key = KEYS[7]

local job_id = ARGV[1]
local request_id = ARGV[2]
local webhook_id = ARGV[3]
local webhook_token = ARGV[4]
local webhook_key = ARGV[5]
local query_string = ARGV[6]
local body_b64 = ARGV[7]
local content_type = ARGV[8]
local source_ip = ARGV[9]
local created_at_ms = ARGV[10]
local body_sha256 = ARGV[11]
local idempotency_value = ARGV[12]
local job_ttl = tonumber(ARGV[13])
local idempotency_ttl = tonumber(ARGV[14])

if idempotency_value ~= '' then
    local existing = redis.call('HGETALL', idem_key)
    if #existing > 0 then
        local existing_body_sha256 = ''
        local existing_request_id = ''
        local existing_job_id = ''
        for index = 1, #existing, 2 do
            if existing[index] == 'body_sha256' then
                existing_body_sha256 = existing[index + 1]
            elseif existing[index] == 'request_id' then
                existing_request_id = existing[index + 1]
            elseif existing[index] == 'job_id' then
                existing_job_id = existing[index + 1]
            end
        end
        if existing_body_sha256 ~= '' and existing_body_sha256 ~= body_sha256 then
            return {'conflict', existing_request_id, existing_job_id, '0'}
        end
        redis.call('HINCRBY', stats_key, 'duplicates', 1)
        redis.call('SADD', unique_key, webhook_key)
        return {'duplicate', existing_request_id, existing_job_id, '0'}
    end
end

redis.call(
    'HSET',
    job_key,
    'job_id', job_id,
    'request_id', request_id,
    'webhook_id', webhook_id,
    'webhook_token', webhook_token,
    'webhook_key', webhook_key,
    'query_string', query_string,
    'body_b64', body_b64,
    'content_type', content_type,
    'source_ip', source_ip,
    'created_at_ms', created_at_ms,
    'available_at_ms', created_at_ms,
    'attempts', '0',
    'last_error', '',
    'last_status', '',
    'body_sha256', body_sha256,
    'idempotency_key', idempotency_value
)
redis.call('EXPIRE', job_key, job_ttl)

local queue_length = redis.call('RPUSH', queue_key, job_id)
redis.call('EXPIRE', queue_key, job_ttl)
redis.call('INCR', pending_key)
redis.call('SADD', unique_key, webhook_key)

if queue_length == 1 then
    redis.call('ZADD', ready_key, tonumber(created_at_ms), webhook_key)
end

if idempotency_value ~= '' then
    redis.call(
        'HSET',
        idem_key,
        'job_id', job_id,
        'request_id', request_id,
        'body_sha256', body_sha256,
        'created_at_ms', created_at_ms
    )
    redis.call('EXPIRE', idem_key, idempotency_ttl)
end

redis.call('HINCRBY', stats_key, 'accepted', 1)

return {'accepted', request_id, job_id, tostring(queue_length)}
"""

def parse_bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def get_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


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


def parse_blacklisted_webhooks(raw: str) -> tuple[set[str], list[str]]:
    blocked: set[str] = set()
    invalid: list[str] = []
    for item in csv_items(raw):
        parsed = parse_webhook_url(item)
        if not parsed:
            invalid.append(item)
            continue
        blocked.add(webhook_key(parsed[0], parsed[1]))
    return blocked, invalid


def parse_ip_networks(raw: str) -> tuple[list[ipaddress._BaseNetwork], list[str]]:
    networks: list[ipaddress._BaseNetwork] = []
    invalid: list[str] = []
    for item in csv_items(raw):
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            invalid.append(item)
    return networks, invalid


def ip_in_networks(ip_value: str, networks: list[ipaddress._BaseNetwork]) -> bool:
    try:
        ip = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    return any(ip in network for network in networks)


class Config:
    def __init__(self) -> None:
        self.redis_url = os.getenv("REDIS_URL", "").strip()
        self.port = max(1, get_int_env("PORT", 8000))
        self.queue_prefix = os.getenv("QUEUE_PREFIX", "discord_proxy").strip() or "discord_proxy"
        self.dispatch_concurrency = max(1, get_int_env("DISPATCH_CONCURRENCY", 8))
        self.queue_scan_limit = max(1, get_int_env("QUEUE_SCAN_LIMIT", 64))
        self.poll_interval_seconds = max(0.05, get_float_env("QUEUE_POLL_INTERVAL_SECONDS", 0.25))
        self.reclaim_interval_seconds = max(1.0, get_float_env("RECLAIM_INTERVAL_SECONDS", 10.0))
        self.http_timeout_seconds = max(5.0, get_float_env("HTTP_TIMEOUT_SECONDS", 20.0))
        self.claim_visibility_seconds = max(
            self.http_timeout_seconds + 10.0,
            get_float_env("CLAIM_VISIBILITY_SECONDS", 120.0),
        )
        self.redis_health_check_interval_seconds = max(5, get_int_env("REDIS_HEALTH_CHECK_INTERVAL_SECONDS", 15))
        self.redis_socket_connect_timeout_seconds = max(1.0, get_float_env("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", 5.0))
        self.redis_socket_timeout_seconds = max(2.0, get_float_env("REDIS_SOCKET_TIMEOUT_SECONDS", 30.0))
        self.trust_proxy_headers = parse_bool(os.getenv("TRUST_PROXY_HEADERS", "true"), True)
        self.max_attempts = max(1, get_int_env("MAX_ATTEMPTS", 8))
        self.base_retry_seconds = max(0.25, get_float_env("BASE_RETRY_SECONDS", 1.5))
        self.max_retry_seconds = max(self.base_retry_seconds, get_float_env("MAX_RETRY_SECONDS", 90.0))
        self.job_ttl_seconds = max(300, get_int_env("JOB_TTL_SECONDS", 172800))
        self.idempotency_ttl_seconds = max(60, get_int_env("IDEMPOTENCY_TTL_SECONDS", 86400))
        self.max_body_bytes = max(1024, get_int_env("MAX_BODY_BYTES", 32 * 1024 * 1024))
        self.max_query_length = max(256, get_int_env("MAX_QUERY_LENGTH", 8192))
        self.max_idempotency_key_length = max(16, get_int_env("MAX_IDEMPOTENCY_KEY_LENGTH", 128))
        self.max_content_type_length = max(32, get_int_env("MAX_CONTENT_TYPE_LENGTH", 200))
        self.deadletter_maxlen = max(100, get_int_env("DEADLETTER_MAXLEN", 10000))
        self.http_max_keepalive_connections = max(10, get_int_env("HTTP_MAX_KEEPALIVE_CONNECTIONS", 200))
        self.http_max_connections = max(self.http_max_keepalive_connections, get_int_env("HTTP_MAX_CONNECTIONS", 400))
        self.webhook_rate_limit_requests = max(1, get_int_env("WEBHOOK_RATE_LIMIT_REQUESTS", 60))
        self.webhook_rate_limit_window_seconds = max(1, get_int_env("WEBHOOK_RATE_LIMIT_WINDOW_SECONDS", 60))
        self.webhook_abuse_block_after = max(1, get_int_env("WEBHOOK_ABUSE_BLOCK_AFTER", 3))
        self.webhook_abuse_base_block_seconds = max(1, get_int_env("WEBHOOK_ABUSE_BASE_BLOCK_SECONDS", 30))
        self.webhook_abuse_max_block_seconds = min(3600, max(self.webhook_abuse_base_block_seconds, get_int_env("WEBHOOK_ABUSE_MAX_BLOCK_SECONDS", 3600)))
        self.webhook_abuse_burst_multiplier = max(1.0, get_float_env("WEBHOOK_ABUSE_BURST_MULTIPLIER", 2.0))
        self.ip_rate_limit_enabled = parse_bool(os.getenv("ENABLE_IP_RATE_LIMIT", "false"))
        self.ip_rate_limit_requests = max(1, get_int_env("IP_RATE_LIMIT_REQUESTS", 240))
        self.ip_rate_limit_window_seconds = max(1, get_int_env("IP_RATE_LIMIT_WINDOW_SECONDS", 60))
        self.ip_abuse_block_after = max(1, get_int_env("IP_ABUSE_BLOCK_AFTER", 5))
        self.ip_abuse_base_block_seconds = max(1, get_int_env("IP_ABUSE_BASE_BLOCK_SECONDS", 30))
        self.ip_abuse_max_block_seconds = min(3600, max(self.ip_abuse_base_block_seconds, get_int_env("IP_ABUSE_MAX_BLOCK_SECONDS", 3600)))
        self.ip_abuse_burst_multiplier = max(1.0, get_float_env("IP_ABUSE_BURST_MULTIPLIER", 3.0))
        self.rate_limit_violation_ttl_seconds = max(60, get_int_env("RATE_LIMIT_VIOLATION_TTL_SECONDS", 3600))
        webhook_blacklist_raw = os.getenv("BlacklistedWebhooks", os.getenv("BLACKLISTED_WEBHOOKS", ""))
        ip_blacklist_raw = os.getenv("BlacklistedIPs", os.getenv("BLACKLISTED_IPS", ""))
        self.blacklisted_webhook_keys, self.invalid_blacklisted_webhooks = parse_blacklisted_webhooks(webhook_blacklist_raw)
        self.blacklisted_ip_networks, self.invalid_blacklisted_ips = parse_ip_networks(ip_blacklist_raw)

        if not self.redis_url:
            raise RuntimeError("REDIS_URL is required for durable replica-safe dispatching.")


class PrettyLogFormatter(logging.Formatter):
    LEVEL_NAMES = {
        "DEBUG": "Trace",
        "INFO": "Info",
        "WARNING": "Warning",
        "ERROR": "Error",
        "CRITICAL": "Critical",
    }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        level = self.LEVEL_NAMES.get(record.levelname, record.levelname.title())
        message = record.getMessage()
        details = getattr(record, "details", {}) or {}
        if not isinstance(details, dict):
            details = {"details": details}
        rendered = " ".join(f"{key}={self._stringify(value)}" for key, value in details.items() if value is not None)
        return f"{timestamp} | {level} | {message}" + (f" | {rendered}" if rendered else "")

    def _stringify(self, value: Any) -> str:
        if isinstance(value, float):
            value = round(value, 3)
        text = str(value)
        if any(character.isspace() for character in text):
            return json.dumps(text, ensure_ascii=False)
        return text


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("discord_proxy")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(PrettyLogFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
    return logger


def now_ms() -> int:
    return int(time.time() * 1000)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def short_hash(value: str) -> str:
    return sha256_text(value)[:12]


def webhook_key(webhook_id: str, webhook_token: str) -> str:
    return sha256_text(f"{webhook_id}:{webhook_token}")


def webhook_ref(webhook_id: str, webhook_token: str) -> str:
    return f"{webhook_id}:{short_hash(webhook_token)}"


def build_discord_url(webhook_id: str, webhook_token: str, query_string: str) -> str:
    base = f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}"
    return f"{base}?{query_string}" if query_string else base


def encode_body(body: bytes) -> str:
    return base64.b64encode(body).decode("ascii")


def decode_body(body_b64: str) -> bytes:
    return base64.b64decode(body_b64.encode("ascii"))


def extract_client_ip(request: Request, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").strip()
        if forwarded:
            forwarded_ip = forwarded.split(",", 1)[0].strip()
            try:
                ipaddress.ip_address(forwarded_ip)
                return forwarded_ip
            except ValueError:
                pass

        x_real_ip = request.headers.get("x-real-ip", "").strip()
        if x_real_ip:
            try:
                ipaddress.ip_address(x_real_ip)
                return x_real_ip
            except ValueError:
                pass

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def normalize_content_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def looks_like_json(body: bytes) -> bool:
    stripped = body.lstrip()
    return stripped.startswith(b"{") or stripped.startswith(b"[")


def get_retry_after_seconds(response: httpx.Response) -> float:
    header_value = response.headers.get("Retry-After")
    if header_value:
        try:
            return max(float(header_value), 0.0)
        except ValueError:
            pass
    try:
        payload = response.json()
        retry_after = payload.get("retry_after")
        if retry_after is not None:
            return max(float(retry_after), 0.0)
    except Exception:
        pass
    reset_after = response.headers.get("X-RateLimit-Reset-After")
    if reset_after:
        try:
            return max(float(reset_after), 0.0)
        except ValueError:
            pass
    return 1.5


def is_global_rate_limited(response: httpx.Response) -> bool:
    if response.headers.get("X-RateLimit-Global", "").lower() == "true":
        return True
    if response.headers.get("X-RateLimit-Scope", "").lower() == "global":
        return True
    try:
        return bool(response.json().get("global") is True)
    except Exception:
        return False


def truncate_text(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def retry_delay_seconds(attempts: int, config: Config) -> float:
    delay = min(config.base_retry_seconds * (2 ** max(attempts - 1, 0)), config.max_retry_seconds)
    jitter_seed = (attempts * 9301 + 49297) % 233280
    jitter = (jitter_seed / 233280.0) * 0.25
    return min(delay + jitter, config.max_retry_seconds)


def integer_dict(values: dict[str, str]) -> dict[str, int]:
    converted: dict[str, int] = {}
    for key, value in values.items():
        try:
            converted[key] = int(value)
        except (TypeError, ValueError):
            converted[key] = 0
    return converted


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large.")
        chunks.append(chunk)
    return b"".join(chunks)


class AppState:
    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.redis = redis.from_url(
            config.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=config.redis_health_check_interval_seconds,
            socket_connect_timeout=config.redis_socket_connect_timeout_seconds,
            socket_timeout=config.redis_socket_timeout_seconds,
            socket_keepalive=True,
            retry_on_timeout=True,
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

    @property
    def ready_webhooks_key(self) -> str:
        return f"{self.config.queue_prefix}:ready:webhooks"

    @property
    def processing_jobs_key(self) -> str:
        return f"{self.config.queue_prefix}:processing:jobs"

    @property
    def deadletter_stream_key(self) -> str:
        return f"{self.config.queue_prefix}:deadletter"

    @property
    def stats_key(self) -> str:
        return f"{self.config.queue_prefix}:stats"

    @property
    def pending_jobs_key(self) -> str:
        return f"{self.config.queue_prefix}:pending:jobs"

    @property
    def unique_webhooks_key(self) -> str:
        return f"{self.config.queue_prefix}:unique:webhooks"

    @property
    def global_backoff_key(self) -> str:
        return f"{self.config.queue_prefix}:discord:global-backoff"

    def job_key(self, job_id: str) -> str:
        return f"{self.config.queue_prefix}:job:{job_id}"

    def webhook_queue_key(self, webhook_key_value: str) -> str:
        return f"{self.config.queue_prefix}:webhook-queue:{webhook_key_value}"

    def claim_key(self, job_id: str) -> str:
        return f"{self.config.queue_prefix}:claim:{job_id}"

    def lock_key(self, webhook_key_value: str) -> str:
        return f"{self.config.queue_prefix}:lock:{webhook_key_value}"

    def idempotency_key(self, webhook_key_value: str, idempotency_key_value: str) -> str:
        return f"{self.config.queue_prefix}:idempotency:{webhook_key_value}:{sha256_text(idempotency_key_value)}"

    def rate_limit_key(self, subject: str, subject_key: str, kind: str) -> str:
        return f"{self.config.queue_prefix}:ratelimit:{subject}:{subject_key}:{kind}"

    def log_sample_key(self, event: str, subject_key: str) -> str:
        return f"{self.config.queue_prefix}:log-sample:{event}:{subject_key}"

    async def start(self) -> None:
        await self.redis.ping()
        self.logger.info(
            "Service ready",
            extra={
                "details": {
                    "instance": self.instance_id,
                    "replica_safe": "true",
                    "dispatch_concurrency": self.config.dispatch_concurrency,
                    "queue_prefix": self.config.queue_prefix,
                    "blacklisted_webhooks": len(self.config.blacklisted_webhook_keys),
                    "blacklisted_ip_rules": len(self.config.blacklisted_ip_networks),
                }
            },
        )
        for invalid in self.config.invalid_blacklisted_webhooks:
            self.logger.warning("Invalid blacklisted webhook ignored", extra={"details": {"entry": truncate_text(invalid)}})
        for invalid in self.config.invalid_blacklisted_ips:
            self.logger.warning("Invalid blacklisted IP rule ignored", extra={"details": {"entry": truncate_text(invalid)}})
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
        self.logger.info("Service stopped", extra={"details": {"instance": self.instance_id}})

    async def increment_stat(self, field: str, amount: int = 1) -> None:
        try:
            await self.redis.hincrby(self.stats_key, field, amount)
        except Exception as exc:
            self.logger.warning("Stat update failed", extra={"details": {"field": field, "error": truncate_text(str(exc))}})

    async def should_log_once(self, event: str, subject_key: str, seconds: int = 60) -> bool:
        try:
            return bool(await self.redis.set(self.log_sample_key(event, subject_key), "1", ex=seconds, nx=True))
        except Exception:
            return True

    async def set_global_backoff(self, delay_seconds: float) -> None:
        ttl_ms = max(1, int((delay_seconds + 0.1) * 1000))
        await self.redis.psetex(self.global_backoff_key, ttl_ms, "1")

    async def sleep_if_global_backoff(self) -> bool:
        ttl_ms = await self.redis.pttl(self.global_backoff_key)
        if ttl_ms and ttl_ms > 0:
            await asyncio.sleep(min(ttl_ms / 1000.0, self.config.poll_interval_seconds))
            return True
        return False

    async def check_rate_limit(
        self,
        subject: str,
        subject_key: str,
        max_requests: int,
        window_seconds: int,
        block_after: int,
        base_block_seconds: int,
        max_block_seconds: int,
        burst_multiplier: float,
    ) -> dict[str, Any]:
        result = await self.redis.eval(
            RATE_LIMIT_LUA,
            3,
            self.rate_limit_key(subject, subject_key, "window"),
            self.rate_limit_key(subject, subject_key, "violations"),
            self.rate_limit_key(subject, subject_key, "block"),
            str(max_requests),
            str(window_seconds),
            str(self.config.rate_limit_violation_ttl_seconds),
            str(block_after),
            str(base_block_seconds),
            str(max_block_seconds),
            str(burst_multiplier),
        )
        allowed, retry_after, blocked, count, limit = result
        return {
            "allowed": int(allowed) == 1,
            "retry_after": int(retry_after),
            "blocked": int(blocked) == 1,
            "count": int(count),
            "limit": int(limit),
        }

    async def claim_next_job(self) -> tuple[str, str] | None:
        result = await self.redis.eval(
            CLAIM_NEXT_JOB_LUA,
            4,
            self.ready_webhooks_key,
            self.processing_jobs_key,
            self.global_backoff_key,
            self.pending_jobs_key,
            str(now_ms()),
            str(self.config.queue_scan_limit),
            self.instance_id,
            str(int(self.config.claim_visibility_seconds * 1000)),
            f"{self.config.queue_prefix}:webhook-queue:",
            f"{self.config.queue_prefix}:job:",
            f"{self.config.queue_prefix}:claim:",
            f"{self.config.queue_prefix}:lock:",
        )
        if not result:
            return None
        job_id, webhook_key_value = result
        return str(job_id), str(webhook_key_value)

    async def finalize_job(self, job_id: str, webhook_key_value: str, delete_job: bool) -> None:
        await self.redis.eval(
            FINALIZE_JOB_LUA,
            3,
            self.ready_webhooks_key,
            self.processing_jobs_key,
            self.pending_jobs_key,
            job_id,
            webhook_key_value,
            f"{self.config.queue_prefix}:webhook-queue:",
            f"{self.config.queue_prefix}:job:",
            f"{self.config.queue_prefix}:claim:",
            f"{self.config.queue_prefix}:lock:",
            "1" if delete_job else "0",
        )

    async def reschedule_job(
        self,
        job_id: str,
        webhook_key_value: str,
        next_available_at_ms: int,
        attempts: int,
        last_error: str,
        last_status: str,
    ) -> None:
        await self.redis.eval(
            RESCHEDULE_JOB_LUA,
            2,
            self.ready_webhooks_key,
            self.processing_jobs_key,
            job_id,
            webhook_key_value,
            str(next_available_at_ms),
            str(attempts),
            last_error,
            last_status,
            str(self.config.job_ttl_seconds),
            f"{self.config.queue_prefix}:webhook-queue:",
            f"{self.config.queue_prefix}:job:",
            f"{self.config.queue_prefix}:claim:",
            f"{self.config.queue_prefix}:lock:",
        )

    async def enqueue_job(
        self,
        webhook_id: str,
        webhook_token: str,
        query_string: str,
        body: bytes,
        content_type: str,
        source_ip: str,
        idempotency_key_value: str | None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        request_id = uuid.uuid4().hex
        created_at_ms = now_ms()
        webhook_key_value = webhook_key(webhook_id, webhook_token)
        body_sha256 = sha256_bytes(body)
        idem_key_name = self.idempotency_key(webhook_key_value, idempotency_key_value) if idempotency_key_value else ""

        result = await self.redis.eval(
            ENQUEUE_JOB_LUA,
            7,
            self.job_key(job_id),
            self.webhook_queue_key(webhook_key_value),
            self.ready_webhooks_key,
            self.pending_jobs_key,
            self.unique_webhooks_key,
            self.stats_key,
            idem_key_name,
            job_id,
            request_id,
            webhook_id,
            webhook_token,
            webhook_key_value,
            query_string,
            encode_body(body),
            content_type,
            source_ip,
            str(created_at_ms),
            body_sha256,
            idempotency_key_value or "",
            str(self.config.job_ttl_seconds),
            str(self.config.idempotency_ttl_seconds),
        )

        result_status = str(result[0])
        result_request_id = str(result[1])
        result_job_id = str(result[2])

        if result_status == "conflict":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conflicting payload for the same idempotency key.",
            )

        return {
            "request_id": result_request_id,
            "duplicate": result_status == "duplicate",
            "job_id": result_job_id,
        }

    async def push_deadletter(
        self,
        job: dict[str, str],
        reason: str,
        status_code: int | None,
        response_excerpt: str,
    ) -> None:
        fields = {
            "job_id": job.get("job_id", ""),
            "request_id": job.get("request_id", ""),
            "webhook_ref": webhook_ref(job["webhook_id"], job["webhook_token"]),
            "reason": reason,
            "status_code": "" if status_code is None else str(status_code),
            "attempts": job.get("attempts", "0"),
            "created_at_ms": job.get("created_at_ms", "0"),
            "finalized_at_ms": str(now_ms()),
            "response_excerpt": response_excerpt,
        }
        await self.redis.xadd(self.deadletter_stream_key, fields, maxlen=self.config.deadletter_maxlen, approximate=True)
        await self.increment_stat("deadletter")

    async def worker_loop(self, worker_index: int) -> None:
        while not self.shutdown_event.is_set():
            try:
                if await self.sleep_if_global_backoff():
                    continue

                claim = await self.claim_next_job()
                if claim is None:
                    await asyncio.sleep(self.config.poll_interval_seconds)
                    continue

                job_id, webhook_key_value = claim
                job = await self.redis.hgetall(self.job_key(job_id))
                if not job:
                    await self.finalize_job(job_id, webhook_key_value, delete_job=False)
                    self.logger.warning(
                        "Claimed job disappeared before processing",
                        extra={"details": {"job_id": job_id, "worker": worker_index}},
                    )
                    continue

                await self.process_job(job, webhook_key_value, worker_index)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.error(
                    "Worker loop fault",
                    extra={"details": {"worker": worker_index, "error": truncate_text(str(exc))}},
                )
                await asyncio.sleep(self.config.poll_interval_seconds)

    async def process_job(self, job: dict[str, str], webhook_key_value: str, worker_index: int) -> None:
        job_id = job["job_id"]
        attempts = int(job.get("attempts", "0"))
        request_id = job.get("request_id", "")
        url = build_discord_url(job["webhook_id"], job["webhook_token"], job.get("query_string", ""))
        body = decode_body(job["body_b64"])
        headers = {
            "Content-Type": job.get("content_type", "application/json"),
            "User-Agent": "discord-webhook-proxy/3.0",
        }

        self.logger.info(
            "Dispatch started",
            extra={
                "details": {
                    "request_id": request_id,
                    "job_id": job_id,
                    "worker": worker_index,
                    "attempt": attempts + 1,
                    "webhook": webhook_ref(job["webhook_id"], job["webhook_token"]),
                    "bytes": len(body),
                }
            },
        )

        try:
            response = await self.http_client.post(url, content=body, headers=headers)
        except httpx.TimeoutException as exc:
            await self.handle_retry(job, webhook_key_value, attempts + 1, "upstream_timeout", "", retry_delay_seconds(attempts + 1, self.config), exc)
            return
        except httpx.RequestError as exc:
            await self.handle_retry(job, webhook_key_value, attempts + 1, "network_error", "", retry_delay_seconds(attempts + 1, self.config), exc)
            return

        status_code = response.status_code
        response_excerpt = truncate_text(response.text.strip()) if response.text else ""

        if 200 <= status_code < 300:
            await self.finalize_job(job_id, webhook_key_value, delete_job=True)
            await self.increment_stat("sent")
            self.logger.info(
                "Webhook sent",
                extra={
                    "details": {
                        "request_id": request_id,
                        "job_id": job_id,
                        "status": status_code,
                        "worker": worker_index,
                        "webhook": webhook_ref(job["webhook_id"], job["webhook_token"]),
                    }
                },
            )
            return

        if status_code == 429:
            retry_after = get_retry_after_seconds(response)
            if is_global_rate_limited(response):
                await self.set_global_backoff(retry_after)
            await self.handle_retry(job, webhook_key_value, attempts + 1, "rate_limited", str(status_code), retry_after, response_excerpt)
            return

        if status_code >= 500 or status_code in {408, 409, 425}:
            await self.handle_retry(
                job,
                webhook_key_value,
                attempts + 1,
                "upstream_error",
                str(status_code),
                retry_delay_seconds(attempts + 1, self.config),
                response_excerpt,
            )
            return

        await self.push_deadletter(job, "non_retryable_upstream_response", status_code, response_excerpt)
        await self.finalize_job(job_id, webhook_key_value, delete_job=True)
        self.logger.error(
            "Webhook rejected by Discord",
            extra={
                "details": {
                    "request_id": request_id,
                    "job_id": job_id,
                    "status": status_code,
                    "webhook": webhook_ref(job["webhook_id"], job["webhook_token"]),
                    "response": response_excerpt or "-",
                }
            },
        )

    async def handle_retry(
        self,
        job: dict[str, str],
        webhook_key_value: str,
        attempts: int,
        reason: str,
        status_value: str,
        delay_seconds: float,
        error_value: Any,
    ) -> None:
        job_id = job["job_id"]
        request_id = job.get("request_id", "")
        if attempts >= self.config.max_attempts:
            response_excerpt = truncate_text(str(error_value))
            await self.push_deadletter(job, f"{reason}_max_attempts_exhausted", int(status_value) if status_value.isdigit() else None, response_excerpt)
            await self.finalize_job(job_id, webhook_key_value, delete_job=True)
            self.logger.error(
                "Webhook permanently failed",
                extra={
                    "details": {
                        "request_id": request_id,
                        "job_id": job_id,
                        "attempts": attempts,
                        "reason": reason,
                        "status": status_value or "-",
                        "webhook": webhook_ref(job["webhook_id"], job["webhook_token"]),
                        "error": response_excerpt,
                    }
                },
            )
            return

        next_available_at = now_ms() + int(delay_seconds * 1000)
        await self.reschedule_job(
            job_id=job_id,
            webhook_key_value=webhook_key_value,
            next_available_at_ms=next_available_at,
            attempts=attempts,
            last_error=truncate_text(str(error_value), 500),
            last_status=status_value,
        )
        await self.increment_stat("retried")
        self.logger.warning(
            "Webhook rescheduled",
            extra={
                "details": {
                    "request_id": request_id,
                    "job_id": job_id,
                    "attempts": attempts,
                    "retry_in_seconds": round(delay_seconds, 3),
                    "reason": reason,
                    "status": status_value or "-",
                    "webhook": webhook_ref(job["webhook_id"], job["webhook_token"]),
                }
            },
        )

    async def reclaim_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(self.config.reclaim_interval_seconds)
                await self.reclaim_expired_jobs()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.error(
                    "Reclaimer fault",
                    extra={"details": {"error": truncate_text(str(exc))}},
                )

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
            claim_ttl = await self.redis.pttl(self.claim_key(job_id))
            if claim_ttl > 0:
                await self.redis.zadd(self.processing_jobs_key, {job_id: now_ms() + claim_ttl})
                continue

            job = await self.redis.hgetall(self.job_key(job_id))
            if not job:
                await self.redis.zrem(self.processing_jobs_key, job_id)
                pending = await self.redis.decr(self.pending_jobs_key)
                if int(pending) < 0:
                    await self.redis.set(self.pending_jobs_key, "0")
                continue

            webhook_key_value = job["webhook_key"]
            await self.redis.hset(self.job_key(job_id), mapping={"available_at_ms": str(now_ms()), "last_error": "reclaimed_after_visibility_timeout"})
            lock_key_name = self.lock_key(webhook_key_value)
            if await self.redis.get(lock_key_name) == job_id:
                await self.redis.delete(lock_key_name)
            await self.redis.zrem(self.processing_jobs_key, job_id)
            await self.redis.zadd(self.ready_webhooks_key, {webhook_key_value: now_ms()})
            reclaimed += 1
            self.logger.warning(
                "Orphaned dispatch reclaimed",
                extra={
                    "details": {
                        "job_id": job_id,
                        "request_id": job.get("request_id", ""),
                        "webhook": webhook_ref(job["webhook_id"], job["webhook_token"]),
                    }
                },
            )

        if reclaimed:
            await self.increment_stat("reclaimed", reclaimed)


def get_state(request: Request) -> AppState:
    state = getattr(request.app.state, "state", None)
    if not state:
        raise RuntimeError("Application state is not initialized.")
    return state


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    logger = configure_logging()
    config = Config()
    state = AppState(config, logger)
    app_instance.state.state = state
    await state.start()
    try:
        yield
    finally:
        await state.stop()


app = FastAPI(
    title="Discord Webhook Proxy",
    description="A Secure, Self-Healing Proxy for Discord Webhooks.",
    version="3.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
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
async def api_stats(request: Request) -> JSONResponse:
    state = get_state(request)
    try:
        stats = integer_dict(await state.redis.hgetall(state.stats_key))
        unique_webhooks = int(await state.redis.scard(state.unique_webhooks_key))
        pending_jobs = int(await state.redis.get(state.pending_jobs_key) or 0)
        ready_webhooks = int(await state.redis.zcard(state.ready_webhooks_key))
        processing_jobs = int(await state.redis.zcard(state.processing_jobs_key))
        requests_served = stats.get("accepted", 0) + stats.get("duplicates", 0)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            headers={"Cache-Control": "no-store"},
            content={
                "unique_webhooks": unique_webhooks,
                "requests_served": requests_served,
                "accepted": stats.get("accepted", 0),
                "duplicates": stats.get("duplicates", 0),
                "sent": stats.get("sent", 0),
                "retried": stats.get("retried", 0),
                "rejected": stats.get("rejected", 0),
                "blocked": stats.get("blocked", 0),
                "rate_limited": stats.get("rate_limited", 0),
                "deadletter": stats.get("deadletter", 0),
                "reclaimed": stats.get("reclaimed", 0),
                "pending_jobs": max(pending_jobs, 0),
                "ready_webhooks": ready_webhooks,
                "processing_jobs": processing_jobs,
            },
        )
    except Exception as exc:
        state.logger.error("Stats endpoint failed", extra={"details": {"error": truncate_text(str(exc))}})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "Stats are temporarily unavailable."},
        )


@app.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    state = get_state(request)
    try:
        await state.redis.ping()
        ready_webhooks = await state.redis.zcard(state.ready_webhooks_key)
        processing_jobs = await state.redis.zcard(state.processing_jobs_key)
        pending_jobs = int(await state.redis.get(state.pending_jobs_key) or 0)
        stats = await state.redis.hgetall(state.stats_key)
        global_backoff_ms = await state.redis.pttl(state.global_backoff_key)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ok",
                "instance": state.instance_id,
                "ready_webhooks": ready_webhooks,
                "processing_jobs": processing_jobs,
                "pending_jobs": max(pending_jobs, 0),
                "global_backoff_ms": max(int(global_backoff_ms), 0),
                "stats": stats,
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "error": truncate_text(str(exc))},
        )


@app.get("/readyz")
async def readyz(request: Request) -> Response:
    state = get_state(request)
    await state.redis.ping()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/webhooks/{full_path:path}", response_class=RedirectResponse, include_in_schema=False)
async def redirect_webhook_get(full_path: str) -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


async def reject_request(
    state: AppState,
    status_code: int,
    error: str,
    stat: str,
    log_message: str,
    details: dict[str, Any],
    retry_after: int | None = None,
) -> JSONResponse:
    await state.increment_stat(stat)
    log_details = dict(details)
    if retry_after is not None:
        log_details["retry_after"] = retry_after
    state.logger.warning(log_message, extra={"details": log_details})
    headers = {"Retry-After": str(max(1, retry_after))} if retry_after is not None else None
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


@app.post("/api/webhooks/{webhook_id}/{webhook_token}")
async def proxy_webhook(
    request: Request,
    webhook_id: str = FastAPIPath(..., pattern=r"^\d+$"),
    webhook_token: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_-]+$"),
) -> JSONResponse:
    state = get_state(request)
    source_ip = extract_client_ip(request, state.config.trust_proxy_headers)
    query_string = request.url.query
    webhook_key_value = webhook_key(webhook_id, webhook_token)
    webhook_reference = webhook_ref(webhook_id, webhook_token)

    if webhook_key_value in state.config.blacklisted_webhook_keys:
        return await reject_request(
            state,
            status.HTTP_403_FORBIDDEN,
            "This webhook is blocked from using the proxy.",
            "blocked",
            "Request blocked",
            {"reason": "blacklisted_webhook", "source_ip": source_ip, "webhook": webhook_reference},
        )

    if ip_in_networks(source_ip, state.config.blacklisted_ip_networks):
        return await reject_request(
            state,
            status.HTTP_403_FORBIDDEN,
            "This IP address is blocked from using the proxy.",
            "blocked",
            "Request blocked",
            {"reason": "blacklisted_ip", "source_ip": source_ip, "webhook": webhook_reference},
        )

    webhook_limit = await state.check_rate_limit(
        "webhook",
        webhook_key_value,
        state.config.webhook_rate_limit_requests,
        state.config.webhook_rate_limit_window_seconds,
        state.config.webhook_abuse_block_after,
        state.config.webhook_abuse_base_block_seconds,
        state.config.webhook_abuse_max_block_seconds,
        state.config.webhook_abuse_burst_multiplier,
    )
    if not webhook_limit["allowed"]:
        event = "webhook_blocked" if webhook_limit["blocked"] else "webhook_rate_limited"
        stat_name = "blocked" if webhook_limit["blocked"] else "rate_limited"
        if await state.should_log_once(event, webhook_key_value):
            state.logger.warning(
                "Request throttled",
                extra={
                    "details": {
                        "reason": event,
                        "source_ip": source_ip,
                        "webhook": webhook_reference,
                        "count": webhook_limit["count"],
                        "limit": webhook_limit["limit"],
                        "retry_after": webhook_limit["retry_after"],
                    }
                },
            )
        await state.increment_stat(stat_name)
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(max(1, webhook_limit["retry_after"]))},
            content={"error": "Temporarily rate limited. Slow down before retrying."},
        )

    if state.config.ip_rate_limit_enabled:
        ip_key = sha256_text(source_ip)
        ip_limit = await state.check_rate_limit(
            "ip",
            ip_key,
            state.config.ip_rate_limit_requests,
            state.config.ip_rate_limit_window_seconds,
            state.config.ip_abuse_block_after,
            state.config.ip_abuse_base_block_seconds,
            state.config.ip_abuse_max_block_seconds,
            state.config.ip_abuse_burst_multiplier,
        )
        if not ip_limit["allowed"]:
            event = "ip_blocked" if ip_limit["blocked"] else "ip_rate_limited"
            stat_name = "blocked" if ip_limit["blocked"] else "rate_limited"
            if await state.should_log_once(event, ip_key):
                state.logger.warning(
                    "Request throttled",
                    extra={
                        "details": {
                            "reason": event,
                            "source_ip": source_ip,
                            "webhook": webhook_reference,
                            "count": ip_limit["count"],
                            "limit": ip_limit["limit"],
                            "retry_after": ip_limit["retry_after"],
                        }
                    },
                )
            await state.increment_stat(stat_name)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(max(1, ip_limit["retry_after"]))},
                content={"error": "Temporarily rate limited. Slow down before retrying."},
            )

    if len(query_string) > state.config.max_query_length:
        return await reject_request(
            state,
            status.HTTP_414_REQUEST_URI_TOO_LONG,
            "Query string too large.",
            "rejected",
            "Request rejected",
            {"reason": "query_too_large", "source_ip": source_ip, "webhook": webhook_reference, "query_length": len(query_string)},
        )

    try:
        body = await read_limited_body(request, state.config.max_body_bytes)
    except HTTPException as exc:
        return await reject_request(
            state,
            exc.status_code,
            str(exc.detail),
            "rejected",
            "Request rejected",
            {"reason": "body_too_large", "source_ip": source_ip, "webhook": webhook_reference},
        )

    if not body:
        return await reject_request(
            state,
            status.HTTP_400_BAD_REQUEST,
            "Empty payload rejected.",
            "rejected",
            "Request rejected",
            {"reason": "empty_body", "source_ip": source_ip, "webhook": webhook_reference},
        )

    content_type = request.headers.get("content-type", "").strip()
    if len(content_type) > state.config.max_content_type_length:
        return await reject_request(
            state,
            status.HTTP_400_BAD_REQUEST,
            "Content-Type header too large.",
            "rejected",
            "Request rejected",
            {"reason": "content_type_too_large", "source_ip": source_ip, "webhook": webhook_reference},
        )

    normalized_content_type = normalize_content_type(content_type)

    if normalized_content_type in {"application/json", "text/json"} or (not normalized_content_type and looks_like_json(body)):
        try:
            json.loads(body)
        except Exception:
            return await reject_request(
                state,
                status.HTTP_400_BAD_REQUEST,
                "Malformed JSON payload rejected.",
                "rejected",
                "Request rejected",
                {"reason": "malformed_json", "source_ip": source_ip, "webhook": webhook_reference},
            )
        if not content_type:
            content_type = "application/json"

    if not content_type:
        content_type = "application/octet-stream"

    idempotency_key_value = request.headers.get("x-idempotency-key") or request.headers.get("idempotency-key")
    if idempotency_key_value and len(idempotency_key_value) > state.config.max_idempotency_key_length:
        return await reject_request(
            state,
            status.HTTP_400_BAD_REQUEST,
            "Idempotency key too large.",
            "rejected",
            "Request rejected",
            {"reason": "idempotency_key_too_large", "source_ip": source_ip, "webhook": webhook_reference},
        )

    try:
        enqueue_result = await state.enqueue_job(
            webhook_id=webhook_id,
            webhook_token=webhook_token,
            query_string=query_string,
            body=body,
            content_type=content_type,
            source_ip=source_ip,
            idempotency_key_value=idempotency_key_value,
        )
    except HTTPException as exc:
        return await reject_request(
            state,
            exc.status_code,
            str(exc.detail),
            "rejected",
            "Request rejected",
            {"reason": "idempotency_conflict", "source_ip": source_ip, "webhook": webhook_reference},
        )

    state.logger.info(
        "Webhook accepted",
        extra={
            "details": {
                "request_id": enqueue_result["request_id"],
                "job_id": enqueue_result["job_id"],
                "duplicate": str(enqueue_result["duplicate"]).lower(),
                "source_ip": source_ip,
                "content_type": normalize_content_type(content_type),
                "bytes": len(body),
                "webhook": webhook_reference,
                "idempotency": "present" if idempotency_key_value else "absent",
            }
        },
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "message": "Accepted",
            "request_id": enqueue_result["request_id"],
            "duplicate": enqueue_result["duplicate"],
        },
    )

@app.get("/{full_path:path}", response_class=RedirectResponse, include_in_schema=False)
async def redirect_unknown_get(full_path: str) -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

