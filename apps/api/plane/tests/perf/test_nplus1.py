"""Task 22: demonstrate N+1 by counting queries at two different row counts.

A claim that something is N+1 is only worth making if the query count grows with
the number of rows. Each row count runs as its own parametrised test so it gets
its own transaction — seeding twice inside one test trips
ProjectUserProperty's unique (user, project) constraint, because
ProjectMember.save() creates that row as a side effect.

Each run appends to nplus1_results.json; the report compares the counts.
"""
import json, os, pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from plane.db.models import Project, ProjectMember
from plane.tests.factories import (
    UserFactory, WorkspaceFactory, WorkspaceMemberFactory,
)

OUT = os.environ.get("NPLUS1_OUT", "nplus1_results.json")


def _append(rec):
    data = []
    if os.path.exists(OUT):
        try:
            data = json.load(open(OUT))
        except Exception:
            data = []
    data.append(rec)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1)


@pytest.mark.django_db
@pytest.mark.parametrize("n_projects", [2, 12])
def test_project_list_query_count(api_client, n_projects):
    """ProjectListSerializer.get_next_work_item_sequence runs one IssueSequence
    aggregate per project. If that is an N+1, the query count tracks n_projects."""
    user = UserFactory()
    ws = WorkspaceFactory(owner=user)
    WorkspaceMemberFactory(workspace=ws, member=user, role=20)
    # Created through the ORM rather than the factories: ProjectFactory declares
    # django_get_or_create on (name, workspace), and ProjectMember.save() creates
    # a ProjectUserProperty row per (user, project) — the combination produced a
    # duplicate-key error on the unique (user, project) constraint.
    for i in range(n_projects):
        project = Project.objects.create(
            name=f"perf-{n_projects}-{i}", identifier=f"P{n_projects}{i}",
            workspace=ws, created_by=user, updated_by=user,
        )
        ProjectMember.objects.get_or_create(
            project=project, member=user, defaults={"role": 20, "sort_order": 65535 + i},
        )

    api_client.force_authenticate(user=user)
    with CaptureQueriesContext(connection) as ctx:
        resp = api_client.get(f"/api/workspaces/{ws.slug}/projects/")

    queries = [q["sql"] for q in ctx.captured_queries]
    seq = [q for q in queries if "issue_sequence" in q.lower()]

    # The previous run recorded rows_returned=null because the payload is not a
    # bare list. Without knowing how many projects came back, a flat query count
    # proves nothing — it is equally consistent with a well-optimised endpoint
    # and with an empty response.
    data = getattr(resp, "data", None)
    if isinstance(data, list):
        returned, shape = len(data), "list"
    elif isinstance(data, dict):
        for key in ("results", "grouped_by", "data"):
            if isinstance(data.get(key), list):
                returned, shape = len(data[key]), f"dict[{key}]"
                break
        else:
            returned, shape = None, f"dict keys={sorted(data)[:6]}"
    else:
        returned, shape = None, type(data).__name__

    rec = {
        "endpoint": "/api/workspaces/<slug>/projects/",
        "serializer": "ProjectListSerializer",
        "rows_seeded": n_projects,
        "status": resp.status_code,
        "total_queries": len(queries),
        "issue_sequence_queries": len(seq),
        "rows_returned": returned,
        "payload_shape": shape,
        "project_table_queries": len([q for q in queries if " projects" in q.lower() or "project\"" in q.lower()]),
    }
    _append(rec)
    print(f"\n[N+1] seeded={n_projects} returned={returned} shape={shape} "
          f"status={resp.status_code} total_queries={len(queries)} "
          f"issue_sequence_queries={len(seq)}")
    assert resp.status_code == 200, resp.status_code
