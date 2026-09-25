"""Read-only live check for the issue 1398 parent/native-child demonstration."""

import argparse
import base64
import hashlib
import json
import time
import urllib.parse
import urllib.request


def verify(base: str, execution: str) -> dict:
    root = base.rstrip("/") + "/executions/" + urllib.parse.quote(execution, safe="")

    def get(path: str) -> dict:
        with urllib.request.urlopen(root + path, timeout=20) as response:
            return json.load(response)

    assert get("")["status"] == "completed", "Workflow did not complete"
    deadline = time.monotonic() + 45
    inventory = get("/session-inventory")
    while not inventory["snapshot"] or inventory["later_evidence_pending"]:
        assert time.monotonic() < deadline, "Inventory did not catch up within 45 seconds"
        time.sleep(1)
        inventory = get("/session-inventory")
    snapshot = inventory["snapshot"]
    assert snapshot["counts"]["gap"] == 0, "Inventory has unresolved evidence gaps"
    prefix = "/session-inventory/" + snapshot["snapshot_id"]

    def page(kind: str) -> list:
        result = get(prefix + "/" + kind)
        assert result["next_after"] is None, "Demo exceeded one bounded page"
        return result["items"]

    captures = page("capture")
    native_ids = {item["node"]["local_id"] for item in captures}
    assert len(native_ids) == 2, "Expected exactly parent and native child"
    spawn = [
        edge
        for edge in page("edge")
        if edge["relation"] == "spawn"
        and edge["parent"]["kind"] == edge["child"]["kind"] == "transcript"
    ]
    assert len(spawn) == 1
    parent, child = spawn[0]["parent"]["local_id"], spawn[0]["child"]["local_id"]
    assert parent != child and {parent, child} == native_ids
    bindings = page("binding")
    assert {item["transcript"]["local_id"] for item in bindings} == native_ids
    assert any(
        item["transcript"]["local_id"] == child
        and any(
            evidence["producer_id"].startswith("child-journal:") for evidence in item["evidence"]
        )
        for item in bindings
    ), "Child was not bound through the durable native hook journal"
    checked = []
    for capture in captures:
        assert capture["destination"] == "local" and capture["availability"] == "present"
        digest = capture["archived_byte_hash"]
        identity = capture["node"]
        query = urllib.parse.urlencode(
            {"harness": identity["harness"], "native_id": identity["local_id"]}
        )
        result = get("/session-transcripts/" + digest + "?" + query)
        assert result["status"] == "present"
        body = base64.b64decode(result["content_base64"], validate=True)
        assert hashlib.sha256(body).hexdigest() == digest
        envelope = json.loads(body)
        assert envelope["session_id"] == identity["local_id"]
        assert "INVENTORY_CHILD_OK" in envelope["raw"]
        checked.append({"native_id": identity["local_id"], "sha256": digest, "bytes": len(body)})
    return {
        "execution_id": execution,
        "snapshot": snapshot,
        "parent": parent,
        "child": child,
        "transcripts": checked,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_id")
    parser.add_argument("--api", default="http://localhost:29137")
    args = parser.parse_args()
    print(json.dumps(verify(args.api, args.execution_id), indent=2))
