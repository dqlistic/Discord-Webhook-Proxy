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
from redis.exceptions import WatchError

WEBHOOK_PATH_RE = re.compile(r"^/api/webhooks/(\d+)/([A-Za-z0-9_-]+)$")
FAVICON_PATH = Path(__file__).with_name("favicon.png")

INDEX_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Discord Webhook Proxy</title>
    <meta name="description" content="A Secure, Self-Healing Proxy for Discord Webhooks.">
    <meta property="og:title" content="Discord Webhook Proxy">
    <meta property="og:description" content="A Secure, Self-Healing Proxy for Discord Webhooks.">
    <meta property="og:type" content="website">
    <meta property="og:image" content="/og-image.png">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="theme-color" content="#5865F2">
    <link rel="icon" type="image/png" href="/favicon.png">
    <style nonce="__NONCE__">
        :root {
            color-scheme: dark;
            --bg: #0b0d12;
            --panel: #1e1f22;
            --panel-2: #2b2d31;
            --panel-3: #313338;
            --border: rgba(255,255,255,0.08);
            --text: #dbdee1;
            --muted: #949ba4;
            --soft: #b5bac1;
            --blurple: #5865f2;
            --blurple-dark: #4752c4;
            --green: #57f287;
            --red: #ed4245;
            --yellow: #fee75c;
            --shadow: 0 28px 80px rgba(0,0,0,0.45);
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
                radial-gradient(circle at 20% 12%, rgba(88,101,242,0.25), transparent 34rem),
                radial-gradient(circle at 88% 8%, rgba(237,66,69,0.18), transparent 28rem),
                linear-gradient(180deg, #080a0f 0%, var(--bg) 42%, #111318 100%);
            color: var(--text);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            overflow-x: hidden;
        }

        body::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background-image:
                linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
            background-size: 38px 38px;
            mask-image: linear-gradient(to bottom, rgba(0,0,0,0.8), transparent 82%);
        }

        a {
            color: inherit;
            text-decoration: none;
        }

        .page {
            width: min(1180px, calc(100% - 32px));
            margin: 0 auto;
            padding: 26px 0 40px;
            position: relative;
            z-index: 1;
        }

        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 18px;
            margin-bottom: 34px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }

        .brand-logo {
            width: 46px;
            height: 46px;
            border-radius: 14px;
            background: rgba(88,101,242,0.13);
            border: 1px solid rgba(88,101,242,0.25);
            box-shadow: 0 0 30px rgba(88,101,242,0.25);
            padding: 7px;
        }

        .brand-title {
            display: grid;
            gap: 2px;
        }

        .brand-title strong {
            font-size: 15px;
            letter-spacing: 0.01em;
            color: #fff;
        }

        .brand-title span {
            color: var(--muted);
            font-size: 12px;
        }

        .nav-actions {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: flex-end;
        }

        .pill-link {
            display: inline-flex;
            align-items: center;
            gap: 9px;
            padding: 10px 13px;
            border-radius: 999px;
            border: 1px solid var(--border);
            background: rgba(30,31,34,0.78);
            color: var(--soft);
            font-size: 13px;
            font-weight: 700;
            transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
        }

        .pill-link:hover {
            transform: translateY(-1px);
            border-color: rgba(88,101,242,0.45);
            background: rgba(43,45,49,0.95);
        }

        .github-cat {
            position: relative;
            width: 20px;
            height: 20px;
            display: inline-grid;
            place-items: center;
        }

        .github-cat svg {
            width: 20px;
            height: 20px;
        }

        .github-cat .paw {
            transform-origin: 15px 7px;
            animation: paw-wave 7.5s ease-in-out infinite;
        }

        @keyframes paw-wave {
            0%, 72%, 100% { transform: rotate(0deg); }
            76% { transform: rotate(-24deg); }
            80% { transform: rotate(18deg); }
            84% { transform: rotate(-18deg); }
            88% { transform: rotate(12deg); }
            92% { transform: rotate(0deg); }
        }

        .hero {
            display: grid;
            grid-template-columns: minmax(0, 1.02fr) minmax(320px, 0.98fr);
            gap: 28px;
            align-items: center;
        }

        .hero-copy {
            padding: 26px 4px;
        }

        .eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: var(--green);
            background: rgba(87,242,135,0.08);
            border: 1px solid rgba(87,242,135,0.18);
            border-radius: 999px;
            padding: 8px 11px;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .pulse {
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: var(--green);
            box-shadow: 0 0 18px rgba(87,242,135,0.65);
            animation: pulse 1.8s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.55; transform: scale(0.72); }
        }

        h1 {
            margin: 18px 0 14px;
            color: #fff;
            font-size: clamp(42px, 7vw, 78px);
            line-height: 0.93;
            letter-spacing: -0.06em;
        }

        .gradient-text {
            background: linear-gradient(90deg, #fff 0%, #d9dcff 36%, #8087ff 70%, #ff7577 100%);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }

        .hero-copy p {
            color: var(--soft);
            line-height: 1.72;
            font-size: 16px;
            max-width: 640px;
            margin: 0 0 22px;
        }

        .hero-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .mini-badge {
            color: var(--muted);
            font-size: 12px;
            border: 1px solid var(--border);
            background: rgba(30,31,34,0.72);
            border-radius: 999px;
            padding: 8px 10px;
            font-weight: 700;
        }

        .terminal {
            border-radius: 22px;
            overflow: hidden;
            background: rgba(30,31,34,0.88);
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: var(--shadow);
            backdrop-filter: blur(18px);
        }

        .terminal-bar {
            height: 48px;
            background: rgba(17,18,20,0.88);
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            padding: 0 16px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }

        .lights {
            display: flex;
            gap: 8px;
        }

        .light {
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }

        .light.red { background: var(--red); box-shadow: 0 0 12px rgba(237,66,69,0.45); }
        .light.yellow { background: var(--yellow); box-shadow: 0 0 12px rgba(254,231,92,0.45); }
        .light.green { background: var(--green); box-shadow: 0 0 12px rgba(87,242,135,0.45); }

        .terminal-title {
            color: var(--muted);
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
            font-size: 12px;
            letter-spacing: 0.08em;
        }

        .compiler {
            padding: 24px;
        }

        .compiler h2 {
            color: #fff;
            margin: 0 0 7px;
            font-size: 22px;
            letter-spacing: -0.02em;
        }

        .compiler-subtitle {
            color: var(--muted);
            margin: 0 0 22px;
            font-size: 14px;
            line-height: 1.6;
        }

        .field {
            display: grid;
            gap: 9px;
            margin-bottom: 18px;
        }

        .field label {
            color: var(--muted);
            font-size: 11px;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }

        .input-wrap {
            position: relative;
        }

        .prompt {
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--blurple);
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
            font-weight: 800;
        }

        input {
            width: 100%;
            min-height: 52px;
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.08);
            background: #111214;
            color: var(--green);
            outline: none;
            padding: 14px 112px 14px 34px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
            font-size: 13px;
            transition: border-color 0.18s ease, box-shadow 0.18s ease;
        }

        input::placeholder {
            color: #5f6570;
        }

        input:focus {
            border-color: rgba(88,101,242,0.85);
            box-shadow: 0 0 0 4px rgba(88,101,242,0.13);
        }

        .button {
            border: 0;
            cursor: pointer;
            border-radius: 14px;
            min-height: 52px;
            display: inline-flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            font-weight: 900;
            color: #fff;
            background: linear-gradient(135deg, var(--blurple), var(--blurple-dark));
            box-shadow: 0 14px 32px rgba(88,101,242,0.27);
            width: 100%;
            transition: transform 0.18s ease, filter 0.18s ease;
        }

        .button:hover {
            transform: translateY(-1px);
            filter: brightness(1.08);
        }

        .copy-button {
            position: absolute;
            right: 6px;
            top: 6px;
            bottom: 6px;
            width: 94px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.08);
            color: #fff;
            background: var(--panel-2);
            font-weight: 900;
            cursor: pointer;
        }

        .copy-button:hover {
            background: var(--panel-3);
        }

        .error {
            display: none;
            color: #ff8587;
            font-size: 12px;
            font-weight: 800;
        }

        .error.visible {
            display: block;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 14px;
            margin-top: 22px;
        }

        .stat-card {
            padding: 16px;
            border: 1px solid rgba(255,255,255,0.08);
            background: rgba(17,18,20,0.58);
            border-radius: 16px;
        }

        .stat-card strong {
            display: block;
            color: #fff;
            font-size: clamp(24px, 3vw, 32px);
            letter-spacing: -0.04em;
        }

        .stat-card span {
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
            line-height: 1.35;
        }

        .section {
            margin-top: 34px;
            border: 1px solid rgba(255,255,255,0.08);
            background: rgba(30,31,34,0.68);
            border-radius: 24px;
            padding: 24px;
            box-shadow: 0 18px 60px rgba(0,0,0,0.22);
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: end;
            margin-bottom: 18px;
        }

        .section h2 {
            color: #fff;
            margin: 0;
            font-size: clamp(24px, 3vw, 34px);
            letter-spacing: -0.04em;
        }

        .section-header p {
            margin: 6px 0 0;
            color: var(--muted);
            line-height: 1.6;
            max-width: 680px;
        }

        .cards {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
        }

        .info-card {
            border: 1px solid rgba(255,255,255,0.08);
            background: rgba(17,18,20,0.45);
            border-radius: 18px;
            padding: 17px;
            min-height: 146px;
        }

        .info-card .icon {
            width: 34px;
            height: 34px;
            border-radius: 11px;
            display: grid;
            place-items: center;
            background: rgba(88,101,242,0.13);
            color: #cdd1ff;
            margin-bottom: 14px;
        }

        .info-card h3 {
            color: #fff;
            margin: 0 0 7px;
            font-size: 15px;
        }

        .info-card p {
            color: var(--muted);
            margin: 0;
            font-size: 13px;
            line-height: 1.58;
        }

        .privacy-grid, .rules-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 14px;
        }

        .privacy-card, .rule-card {
            border: 1px solid rgba(255,255,255,0.08);
            background: rgba(17,18,20,0.45);
            border-radius: 18px;
            padding: 18px;
        }

        .privacy-card h3, .rule-card h3 {
            color: #fff;
            margin: 0 0 10px;
            font-size: 15px;
        }

        .privacy-card p, .rule-card p {
            color: var(--muted);
            margin: 0;
            line-height: 1.58;
            font-size: 13px;
        }

        .footer {
            margin-top: 30px;
            padding: 22px 0 4px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            color: var(--muted);
            font-size: 13px;
            flex-wrap: wrap;
        }

        .credit {
            display: inline-flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        .credit strong {
            color: #fff;
        }

        @media (max-width: 980px) {
            .hero {
                grid-template-columns: 1fr;
            }

            .cards {
                grid-template-columns: repeat(2, 1fr);
            }

            .privacy-grid, .rules-grid {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 680px) {
            .page {
                width: min(100% - 22px, 1180px);
                padding-top: 18px;
            }

            .nav, .section-header {
                align-items: flex-start;
                flex-direction: column;
            }

            .nav-actions {
                justify-content: flex-start;
            }

            .compiler {
                padding: 18px;
            }

            input {
                padding-right: 94px;
                font-size: 12px;
            }

            .copy-button {
                width: 78px;
            }

            .stats-grid, .cards {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <main class="page">
        <nav class="nav" aria-label="Primary">
            <a class="brand" href="/" aria-label="Discord Webhook Proxy home">
                <img class="brand-logo" src="/favicon.png" alt="">
                <span class="brand-title">
                    <strong>Discord Webhook Proxy</strong>
                    <span>Queue-safe relay for Discord webhook workloads</span>
                </span>
            </a>
            <div class="nav-actions">
                <a class="pill-link" href="https://devforum.roblox.com/t/release-discord-webhook-proxy-your-webhooks-turbocharged/4647835/1" target="_blank" rel="noopener noreferrer">DevForum Release</a>
                <a class="pill-link" href="https://github.com/dqlistic/Discord-Webhook-Proxy" target="_blank" rel="noopener noreferrer" aria-label="GitHub repository">
                    <span class="github-cat" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                            <path d="M12 2.25c-5.52 0-10 4.48-10 10 0 4.42 2.86 8.16 6.84 9.49.5.09.68-.22.68-.48 0-.23-.01-.86-.01-1.69-2.78.6-3.37-1.19-3.37-1.19-.45-1.15-1.11-1.46-1.11-1.46-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.08.63-1.33-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.64 0 0 .84-.27 2.75 1.02A9.52 9.52 0 0 1 12 7.22c.85 0 1.7.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.37.2 2.39.1 2.64.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.86 0 1.34-.01 2.42-.01 2.75 0 .27.18.58.69.48A10.01 10.01 0 0 0 22 12.25c0-5.52-4.48-10-10-10Z"/>
                            <path class="paw" d="M17.3 4.25c.72-.28 1.55-.24 2.17.18.34.24.41.72.17 1.06-.23.33-.7.42-1.04.2-.22-.15-.57-.16-.84-.06-.38.14-.82-.05-.97-.44-.14-.38.05-.81.51-.94Z"/>
                        </svg>
                    </span>
                    GitHub
                </a>
            </div>
        </nav>

        <section class="hero">
            <div class="hero-copy">
                <span class="eyebrow"><span class="pulse"></span> Live edge proxy</span>
                <h1><span class="gradient-text">Self-Healing Discord Webhook Delivery.</span></h1>
                <p>Paste a Discord webhook, compile it into a proxy endpoint, and let the service absorb bursts with a durable Redis queue, adaptive backoff, and replica-safe workers.</p>
                <div class="hero-badges">
                    <span class="mini-badge">Redis-backed FIFO</span>
                    <span class="mini-badge">Discord-aware 429 handling</span>
                    <span class="mini-badge">Adaptive abuse blocks</span>
                    <span class="mini-badge">Railway replica-ready</span>
                </div>
            </div>

            <section class="terminal" aria-label="Webhook compiler">
                <div class="terminal-bar">
                    <div class="lights">
                        <span class="light red"></span>
                        <span class="light yellow"></span>
                        <span class="light green"></span>
                    </div>
                    <span class="terminal-title">proxy.compiler</span>
                    <span></span>
                </div>
                <div class="compiler">
                    <h2>Compile your endpoint</h2>
                    <p class="compiler-subtitle">Your original token is kept in the generated URL. Never share it with people who should not post to that channel.</p>

                    <div class="field">
                        <label for="webhook-input">Original Discord webhook URL</label>
                        <div class="input-wrap">
                            <span class="prompt">&gt;</span>
                            <input id="webhook-input" type="text" placeholder="https://discord.com/api/webhooks/..." autocomplete="off" spellcheck="false">
                        </div>
                        <span id="error-msg" class="error">Invalid Discord domain or webhook path.</span>
                    </div>

                    <button id="compile-btn" class="button" type="button">Compile Proxy Endpoint</button>

                    <div class="field" style="margin-top:18px">
                        <label for="webhook-output">Proxy endpoint</label>
                        <div class="input-wrap">
                            <span class="prompt">~</span>
                            <input id="webhook-output" type="text" readonly placeholder="Awaiting compilation...">
                            <button id="copy-btn" class="copy-button" type="button">Copy</button>
                        </div>
                    </div>

                    <div class="stats-grid" aria-label="Live service counters">
                        <div class="stat-card">
                            <strong id="unique-webhooks">0</strong>
                            <span>unique webhooks protected</span>
                        </div>
                        <div class="stat-card">
                            <strong id="requests-served">0</strong>
                            <span>requests accepted by the edge</span>
                        </div>
                        <div class="stat-card">
                            <strong id="sent-count">0</strong>
                            <span>dispatches sent to Discord</span>
                        </div>
                    </div>
                </div>
            </section>
        </section>

        <section class="section" id="information">
            <div class="section-header">
                <div>
                    <h2>Built for noisy, real-world traffic.</h2>
                    <p>Short bursts get queued, abusive loops get slowed, and every replica coordinates through Redis so workers do not fight each other.</p>
                </div>
            </div>
            <div class="cards">
                <article class="info-card">
                    <div class="icon">⏱</div>
                    <h3>Rate-limit aware</h3>
                    <p>Reads Discord retry headers and backs off instead of hard-coding fragile limits.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🧵</div>
                    <h3>Per-webhook FIFO</h3>
                    <p>Each webhook gets an ordered queue so bursts stay predictable and isolated.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🛡</div>
                    <h3>Adaptive abuse shield</h3>
                    <p>Repeated over-limit traffic is temporarily ignored for up to one hour.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🔁</div>
                    <h3>Self-healing workers</h3>
                    <p>Timed-out claims are reclaimed so crashed replicas do not strand jobs.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🚄</div>
                    <h3>Replica-safe Railway</h3>
                    <p>Atomic Redis scripts coordinate locks, claims, stats, and queue state.</p>
                </article>
                <article class="info-card">
                    <div class="icon">🚫</div>
                    <h3>Blacklists</h3>
                    <p>Optional webhook and IP/CIDR blocklists stop known bad actors early.</p>
                </article>
                <article class="info-card">
                    <div class="icon">📦</div>
                    <h3>Payload guardrails</h3>
                    <p>Oversized, empty, malformed, or conflicting requests are rejected before dispatch.</p>
                </article>
                <article class="info-card">
                    <div class="icon">📟</div>
                    <h3>Clean logs</h3>
                    <p>Structured, readable events make warnings and failures easy to trace.</p>
                </article>
            </div>
        </section>

        <section class="section" id="privacy">
            <div class="section-header">
                <div>
                    <h2>Data Handling</h2>
                    <p>Transparent storage and processing boundaries for everyone using the public proxy.</p>
                </div>
            </div>
            <div class="privacy-grid">
                <article class="privacy-card">
                    <h3>Stored Permanently</h3>
                    <p>Aggregate counters, capped diagnostic events, and irreversible webhook fingerprints used for the unique webhook counter.</p>
                </article>
                <article class="privacy-card">
                    <h3>Stored Temporarily</h3>
                    <p>Queued payloads, webhook tokens, source IPs, idempotency records, and retry metadata until dispatch or TTL expiry.</p>
                </article>
                <article class="privacy-card">
                    <h3>Processed in Transit</h3>
                    <p>Request body, content type, query string, webhook ID/token, Discord responses, and rate-limit headers.</p>
                </article>
            </div>
        </section>

        <section class="section" id="rules">
            <div class="section-header">
                <div>
                    <h2>Rules & Regulations</h2>
                    <p>Use the proxy like any other shared infrastructure: respectful, lawful, and compatible with Discord’s platform expectations.</p>
                </div>
            </div>
            <div class="rules-grid">
                <article class="rule-card">
                    <h3>No Spamming or Flooding</h3>
                    <p>Do not intentionally overload webhooks, Discord, Railway, Redis, or this proxy.</p>
                </article>
                <article class="rule-card">
                    <h3>Use Your Own Webhooks</h3>
                    <p>Only utilise Discord or proxy webhook URLs you created or are explicitly authorized to use.</p>
                </article>
                <article class="rule-card">
                    <h3>Respect Platform Terms</h3>
                    <p>No abuse, harassment, illegal content, credential leakage, or evasive automation.</p>
                </article>
            </div>
        </section>

        <footer class="footer">
            <span>Proxy status: <strong style="color:var(--green)">Online</strong></span>
            <span class="credit">Architect: <strong>Yee Sen</strong><span>Discord: <strong style="color:var(--blurple)">@yeetysenny</strong></span></span>
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
                if (!isDiscordHostname(original.hostname)) {
                    throw new Error("Invalid host");
                }
                if (!/^\\/api\\/webhooks\\/\\d+\\/[A-Za-z0-9_-]+$/.test(original.pathname)) {
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
        setInterval(refreshStats, 3000);
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

local head = redis.call('LINDEX', queue_key, 0)
if head == job_id then
    redis.call('LPOP', queue_key)
else
    redis.call('LREM', queue_key, 1, job_id)
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
        self.claim_visibility_seconds = max(30.0, get_float_env("CLAIM_VISIBILITY_SECONDS", 120.0))
        self.http_timeout_seconds = max(5.0, get_float_env("HTTP_TIMEOUT_SECONDS", 20.0))
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


def extract_client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    x_real_ip = request.headers.get("x-real-ip", "").strip()
    if x_real_ip:
        return x_real_ip
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
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
        self.redis = redis.from_url(config.redis_url, encoding="utf-8", decode_responses=True, health_check_interval=30)
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
        job_record = {
            "job_id": job_id,
            "request_id": request_id,
            "webhook_id": webhook_id,
            "webhook_token": webhook_token,
            "webhook_key": webhook_key_value,
            "query_string": query_string,
            "body_b64": encode_body(body),
            "content_type": content_type,
            "source_ip": source_ip,
            "created_at_ms": str(created_at_ms),
            "available_at_ms": str(created_at_ms),
            "attempts": "0",
            "last_error": "",
            "last_status": "",
            "body_sha256": body_sha256,
            "idempotency_key": idempotency_key_value or "",
        }
        job_key_name = self.job_key(job_id)
        webhook_queue_key_name = self.webhook_queue_key(webhook_key_value)

        if not idempotency_key_value:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.hset(job_key_name, mapping=job_record)
                pipe.expire(job_key_name, self.config.job_ttl_seconds)
                pipe.rpush(webhook_queue_key_name, job_id)
                pipe.expire(webhook_queue_key_name, self.config.job_ttl_seconds)
                pipe.incr(self.pending_jobs_key)
                pipe.sadd(self.unique_webhooks_key, webhook_key_value)
                results = await pipe.execute()
            queue_length = int(results[2])
            if queue_length == 1:
                await self.redis.zadd(self.ready_webhooks_key, {webhook_key_value: created_at_ms})
            await self.increment_stat("accepted")
            return {"request_id": request_id, "duplicate": False, "job_id": job_id}

        idem_key_name = self.idempotency_key(webhook_key_value, idempotency_key_value)

        while True:
            try:
                async with self.redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(idem_key_name)
                    existing = await pipe.hgetall(idem_key_name)
                    if existing:
                        await pipe.unwatch()
                        existing_body_hash = existing.get("body_sha256", "")
                        if existing_body_hash and existing_body_hash != body_sha256:
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail="Conflicting payload for the same idempotency key.",
                            )
                        await self.increment_stat("duplicates")
                        await self.redis.sadd(self.unique_webhooks_key, webhook_key_value)
                        return {
                            "request_id": existing.get("request_id", ""),
                            "duplicate": True,
                            "job_id": existing.get("job_id", ""),
                        }

                    pipe.multi()
                    pipe.hset(job_key_name, mapping=job_record)
                    pipe.expire(job_key_name, self.config.job_ttl_seconds)
                    pipe.rpush(webhook_queue_key_name, job_id)
                    pipe.expire(webhook_queue_key_name, self.config.job_ttl_seconds)
                    pipe.incr(self.pending_jobs_key)
                    pipe.sadd(self.unique_webhooks_key, webhook_key_value)
                    pipe.hset(
                        idem_key_name,
                        mapping={
                            "job_id": job_id,
                            "request_id": request_id,
                            "body_sha256": body_sha256,
                            "created_at_ms": str(created_at_ms),
                        },
                    )
                    pipe.expire(idem_key_name, self.config.idempotency_ttl_seconds)
                    results = await pipe.execute()
                queue_length = int(results[2])
                if queue_length == 1:
                    await self.redis.zadd(self.ready_webhooks_key, {webhook_key_value: created_at_ms})
                await self.increment_stat("accepted")
                return {"request_id": request_id, "duplicate": False, "job_id": job_id}
            except WatchError:
                continue

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


@app.get("/api/webhooks/{webhook_id}/{webhook_token}", response_class=RedirectResponse)
async def redirect_webhook_get(
    webhook_id: str = FastAPIPath(..., pattern=r"^\d+$"),
    webhook_token: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_-]+$"),
) -> RedirectResponse:
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
    source_ip = extract_client_ip(request)
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
