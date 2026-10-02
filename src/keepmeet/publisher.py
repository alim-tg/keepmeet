import re
from html import escape

import requests

from .config import Config
from .confluence_auth import ConfluenceAuthError, auth_headers, load_credentials, parse_target


class PublishError(Exception):
    pass


def resolve_target(config: Config) -> dict:
    from .settings import load_settings

    url = load_settings(config)["confluence"]["target_url"]
    if url:
        try:
            return parse_target(url)
        except ConfluenceAuthError as e:
            raise PublishError(str(e)) from e
    base = (config.confluence_base_url or "").rstrip("/")
    if base.endswith("/wiki"):
        base = base[: -len("/wiki")]
    return {
        "base_url": base,
        "space_key": config.confluence_space_key,
        "parent_id": config.confluence_parent_page_id,
        "parent_name": None,
    }


def publish_to_confluence(title: str, body_markdown: str, config: Config, meta: dict | None = None) -> str:
    target = resolve_target(config)
    if not target.get("base_url") or not target.get("space_key"):
        raise PublishError("Confluence destination is not set. Add the folder link in Settings.")
    try:
        creds = load_credentials(config)
    except ConfluenceAuthError as e:
        raise PublishError(str(e)) from e
    if not creds:
        raise PublishError("Confluence is not connected. Connect your account in Settings.")

    headers = {**auth_headers(*creds), "Content-Type": "application/json"}
    base = target["base_url"]
    space_id = _space_id(base, target["space_key"], headers)
    storage_body = markdown_to_confluence_storage(body_markdown, meta)

    existing = _find_page(base, space_id, title, headers)
    if existing:
        return _update_page(base, existing["id"], title, storage_body, headers)
    return _create_page(base, space_id, target.get("parent_id"), title, storage_body, headers)


def _request(method: str, url: str, headers: dict, action: str, **kwargs) -> dict:
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    except requests.RequestException as e:
        raise PublishError(f"Failed to {action}: {e}") from e
    if resp.status_code in (401, 403):
        raise PublishError(f"Failed to {action}: Confluence denied access ({resp.status_code}). Reconnect in Settings or check your permissions.")
    if resp.status_code >= 400:
        raise PublishError(f"Failed to {action}: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def _space_id(base: str, space_key: str, headers: dict) -> str:
    data = _request("GET", f"{base}/wiki/api/v2/spaces", headers, "look up the space", params={"keys": space_key})
    results = data.get("results", [])
    if not results:
        raise PublishError(f"Confluence space {space_key} not found or not accessible")
    return results[0]["id"]


def _find_page(base: str, space_id: str, title: str, headers: dict) -> dict | None:
    data = _request(
        "GET", f"{base}/wiki/api/v2/pages", headers, "search Confluence pages",
        params={"space-id": space_id, "title": title, "status": "current"},
    )
    results = data.get("results", [])
    return results[0] if results else None


def _page_url(base: str, data: dict) -> str:
    return f"{base}/wiki{data.get('_links', {}).get('webui', '')}"


def _create_page(base: str, space_id: str, parent_id: str | None, title: str, storage_body: str, headers: dict) -> str:
    payload: dict = {
        "spaceId": space_id,
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": storage_body},
    }
    if parent_id:
        payload["parentId"] = parent_id
    return _page_url(base, _request("POST", f"{base}/wiki/api/v2/pages", headers, "create the Confluence page", json=payload))


def _update_page(base: str, page_id: str, title: str, storage_body: str, headers: dict) -> str:
    current = _request("GET", f"{base}/wiki/api/v2/pages/{page_id}", headers, "read the existing page")
    version = current.get("version", {}).get("number", 1)
    payload = {
        "id": page_id,
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": storage_body},
        "version": {"number": version + 1, "message": "Updated by keepmeet"},
    }
    return _page_url(base, _request("PUT", f"{base}/wiki/api/v2/pages/{page_id}", headers, "update the Confluence page", json=payload))


PANELS = {
    "summary": "info",
    "key points": "info",
    "decisions": "tip",
    "key decisions": "tip",
    "blockers": "note",
    "blockers & risks": "note",
    "blockers and risks": "note",
    "risks": "note",
}
TASK_RE = re.compile(r"^\[( |x|X)\]\s+")


def _markdown_parser():
    from markdown_it import MarkdownIt

    md = MarkdownIt("commonmark", {"html": False, "xhtmlOut": True, "breaks": False})
    md.enable(["table", "strikethrough"])
    return md


def _mark_task_lists(tokens) -> None:
    for i, tok in enumerate(tokens):
        if tok.type != "bullet_list_open":
            continue
        level = tok.level
        items = []
        j = i + 1
        while j < len(tokens) and not (tokens[j].type == "bullet_list_close" and tokens[j].level == level):
            if tokens[j].type == "list_item_open" and tokens[j].level == level + 1:
                inline = next(
                    (t for t in tokens[j + 1:] if t.type == "inline" and t.level == level + 3),
                    None,
                )
                items.append((tokens[j], inline))
            j += 1
        if not items or not all(inline is not None and TASK_RE.match(inline.content) for _, inline in items):
            continue
        tok.meta["task"] = True
        tokens[j].meta["task"] = True
        for item, inline in items:
            done = TASK_RE.match(inline.content).group(1).lower() == "x"
            item.meta["task"] = "complete" if done else "incomplete"
            inline.content = TASK_RE.sub("", inline.content, count=1)
            if inline.children and inline.children[0].type == "text":
                inline.children[0].content = TASK_RE.sub("", inline.children[0].content, count=1)


def _install_task_rules(md):
    def bullet_open(renderer, tokens, idx, options, env):
        if tokens[idx].meta.get("task"):
            return "<ac:task-list>\n"
        return renderer.renderToken(tokens, idx, options, env)

    def bullet_close(renderer, tokens, idx, options, env):
        if tokens[idx].meta.get("task"):
            return "</ac:task-list>\n"
        return renderer.renderToken(tokens, idx, options, env)

    def item_open(renderer, tokens, idx, options, env):
        state = tokens[idx].meta.get("task")
        if state:
            return f"<ac:task>\n<ac:task-status>{state}</ac:task-status>\n<ac:task-body>"
        return renderer.renderToken(tokens, idx, options, env)

    def item_close(renderer, tokens, idx, options, env):
        opener = next(
            (t for t in reversed(tokens[:idx]) if t.type == "list_item_open" and t.level == tokens[idx].level),
            None,
        )
        if opener is not None and opener.meta.get("task"):
            return "</ac:task-body>\n</ac:task>\n"
        return renderer.renderToken(tokens, idx, options, env)

    md.add_render_rule("bullet_list_open", bullet_open)
    md.add_render_rule("bullet_list_close", bullet_close)
    md.add_render_rule("list_item_open", item_open)
    md.add_render_rule("list_item_close", item_close)


def _render(md, text: str) -> str:
    tokens = md.parse(text)
    _mark_task_lists(tokens)
    return md.renderer.render(tokens, md.options, {})


def _split_sections(md_text: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in md_text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            sections.append((heading.group(1), []))
        else:
            sections[-1][1].append(line)
    return [(title, "\n".join(lines)) for title, lines in sections]


def _panel(kind: str, title: str, body_html: str) -> str:
    return (
        f'<ac:structured-macro ac:name="{kind}">'
        f'<ac:parameter ac:name="title">{escape(title)}</ac:parameter>'
        f"<ac:rich-text-body>{body_html}</ac:rich-text-body>"
        "</ac:structured-macro>"
    )


def _meta_table(meta: dict) -> str:
    rows = [(label, value) for label, value in (
        ("Date", meta.get("date")),
        ("Participants", ", ".join(meta.get("participants") or [])),
        ("Duration", meta.get("duration")),
    ) if value]
    if not rows:
        return ""
    cells = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows)
    return f"<table><tbody>{cells}</tbody></table>"


def markdown_to_confluence_storage(md_text: str, meta: dict | None = None) -> str:
    md = _markdown_parser()
    _install_task_rules(md)
    md_text = re.sub(r"\A\s*#\s+[^\n]*\n", "", md_text)

    parts = []
    if meta:
        parts.append(_meta_table(meta))
    for title, body in _split_sections(md_text):
        body_html = _render(md, body).strip()
        if title is None:
            if body_html:
                parts.append(body_html)
            continue
        kind = PANELS.get(title.strip().lower())
        if kind and body_html:
            parts.append(_panel(kind, title.strip(), body_html))
        else:
            parts.append(f"<h2>{escape(title.strip())}</h2>{body_html}")
    parts.append("<p><em>Generated by keepmeet from the meeting recording.</em></p>")
    return "\n".join(p for p in parts if p)
