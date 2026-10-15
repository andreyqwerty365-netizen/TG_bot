from sqlalchemy import event,insert
from personal_crm.models import SourceVersion,Task,uid
from test_core import OWNER,ingest


def test_today_does_not_materialize_unselected_undated_backlog(factory,service,clock):
    source,first=ingest(service)
    with factory.begin() as s:
        source_id=s.get(SourceVersion,source).source_id;identities=[uid() for _ in range(500)]
        s.execute(insert(SourceVersion),[dict(id=identity,source_id=source_id,revision=index+2,
            text='Synthetic backlog',status='processed',received_at=clock.now) for index,identity in enumerate(identities)])
        s.execute(insert(Task),[dict(id=uid(),owner_id=OWNER,source_version_id=identity,
            title=f'Synthetic backlog {index}',title_search=f'synthetic backlog {index}',created_at=clock.now)
            for index,identity in enumerate(identities)])
    loaded=[]
    def observe(session,value):
        if isinstance(value,Task):loaded.append(value.id)
    event.listen(factory,'loaded_as_persistent',observe)
    try:
        view=service.overview(OWNER)
    finally:event.remove(factory,'loaded_as_persistent',observe)
    assert view['other_count']==499 and len(view['forgotten'])==2
    assert len(set(loaded))<=2
