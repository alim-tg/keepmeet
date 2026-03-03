import base64
import re

import requests

from .config import Config


class PublishError(Exception):
    pass


def publish_to_confluence(title: str, body_markdown: str, config: Config) -> str:
    if not config.confluence_base_url or not config.confluence_api_token:
        raise PublishError(
            "Confluence is not configured. "
            "Set confluence_base_url in config.yaml and CONFLUENCE_API_TOKEN in .env"
        )

    headers = _auth_headers(config)
    storage_body = markdown_to_confluence_storage(body_markdown)

    existing = _find_page(title, config, headers)
    if existing:
        return _update_page(existing, title, storage_body, config, headers)
    return _create_page(title, storage_body, config, headers)


def _auth_headers(config: Config) -> dict[str, str]:
    creds = f"{config.confluence_email}:{config.confluence_api_token}"
    token = base64.b64encode(creds.encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


def _find_page(
    title: str, config: Config, headers: dict[str, str]
) -> dict | None:
    url = f"{config.confluence_base_url}/wiki/api/v2/pages"
    params = {"spaceId": config.confluence_space_key, "title": title}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise PublishError(f"Failed to search Confluence pages: {e}") from e

    results = resp.json().get("results", [])
    return results[0] if results else None


def _create_page(
    title: str,
    storage_body: str,
    config: Config,
    headers: dict[str, str],
) -> str:
    url = f"{config.confluence_base_url}/wiki/api/v2/pages"
    payload: dict = {
        "spaceId": config.confluence_space_key,
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": storage_body},
    }
    if config.confluence_parent_page_id:
        payload["parentId"] = config.confluence_parent_page_id

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise PublishError(f"Failed to create Confluence page: {e}") from e

    web_link = resp.json().get("_links", {}).get("webui", "")
    return f"{config.confluence_base_url}/wiki{web_link}"


def _update_page(
    existing: dict,
    title: str,
    storage_body: str,
    config: Config,
    headers: dict[str, str],
) -> str:
    page_id = existing["id"]
    version = existing.get("version", {}).get("number", 1)
    url = f"{config.confluence_base_url}/wiki/api/v2/pages/{page_id}"
    payload = {
        "id": page_id,
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": storage_body},
        "version": {"number": version + 1},
    }

    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise PublishError(f"Failed to update Confluence page: {e}") from e

    web_link = resp.json().get("_links", {}).get("webui", "")
    return f"{config.confluence_base_url}/wiki{web_link}"


def markdown_to_confluence_storage(md: str) -> str:
    lines = md.split("\n")
    html_parts: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            level = len(heading_match.group(1))
            text = _inline_format(heading_match.group(2))
            html_parts.append(f"<h{level}>{text}</h{level}>")
            continue

        if stripped.startswith(("- ", "* ")):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            item_text = _inline_format(stripped[2:])
            html_parts.append(f"<li>{item_text}</li>")
            continue

        if in_list:
            html_parts.append("</ul>")
            in_list = False
        html_parts.append(f"<p>{_inline_format(stripped)}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def _inline_format(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text
