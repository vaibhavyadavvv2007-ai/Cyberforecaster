"""Search YouTube via curl (JS-rendered pages are useless with WebFetch) and
print structured results: title | channel | duration | views | URL.

Usage: python scripts/yt_search.py "query" [n]
"""
import json
import re
import subprocess
import sys
import urllib.parse


def search(query: str, n: int = 8) -> list[dict]:
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    html = subprocess.run(
        ["curl", "-s", "-A",
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36", url],
        capture_output=True, text=True).stdout
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    out = []
    contents = data["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
        "sectionListRenderer"]["contents"]
    for section in contents:
        for item in section.get("itemSectionRenderer", {}).get("contents", []):
            v = item.get("videoRenderer")
            if not v:
                continue
            out.append({
                "title": "".join(r["text"] for r in
                                 v["title"]["runs"]),
                "channel": "".join(r["text"] for r in
                                   v.get("ownerText", {}).get("runs", [])),
                "duration": v.get("lengthText", {}).get("simpleText", "?"),
                "views": v.get("viewCountText", {}).get("simpleText", "?"),
                "url": f"https://www.youtube.com/watch?v={v['videoId']}",
            })
            if len(out) >= n:
                return out
    return out


if __name__ == "__main__":
    q = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    for r in search(q, n):
        print(f"{r['title']}  |  {r['channel']}  |  {r['duration']}  |  {r['views']}")
        print(f"   {r['url']}")
