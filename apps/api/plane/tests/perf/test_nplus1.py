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

from plane.tests.factories import (
    UserFactory, WorkspaceFactory, WorkspaceMemberFactory,
    ProjectFactory, ProjectMemberFactory,
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
    for _ in range(n_projects):
        project = ProjectFactory(workspace=ws)
        ProjectMemberFactory(project=project, member=user, role=20)

    api_client.force_authenticate(user=user)
    with CaptureQueriesContext(connection) as ctx:
        resp = api_client.get(f"/api/workspaces/{ws.slug}/projects/")

    queries = [q["sql"] for q in ctx.captured_queries]
    seq = [q for q in queries if "issue_sequence" in q.lower()]
    rec = {
        "endpoint": "/api/workspaces/<slug>/projects/",
        "serializer": "ProjectListSerializer",
        "rows": n_projects,
        "status": resp.status_code,
        "total_queries": len(queries),
        "issue_sequence_queries": len(seq),
        "rows_returned": len(resp.data) if hasattr(resp, "data") and isinstance(resp.data, list) else None,
    }
    _append(rec)
    print(f"\n[N+1] projects={n_projects} status={resp.status_code} "
          f"total_queries={len(queries)} issue_sequence_queries={len(seq)}")
    assert resp.status_code == 200, resp.status_code
