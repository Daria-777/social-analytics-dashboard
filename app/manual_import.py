"""Exact parent IDs, atomic batch, new observations only; no reconciliation."""
from sqlalchemy import select
from app.models import SocialAccount,Content,AccountSnapshot,ContentSnapshot,ContentRetentionSnapshot,ContentGeoSnapshot
from app.enums import Source
from app.connectors.instagram.mapper import sanitize


class ImportMissingError(ValueError): pass
class ImportIdentityError(ValueError): pass


def import_batch(db,batch):
    rows={'content':[],'account':[],'retention':[]}
    try:
        for records,model,parent_model,parent_field,selector,label in (
            (batch.content_snapshots,ContentSnapshot,Content,'content_id','platform_content_id','content'),
            (batch.account_snapshots,AccountSnapshot,SocialAccount,'account_id','platform_account_id','account'),
            (batch.retention_snapshots,ContentRetentionSnapshot,Content,'content_id','platform_content_id','retention'),
        ):
            for record in records:
                parent=db.scalar(select(parent_model).where(parent_model.platform==record.platform,getattr(parent_model,selector)==getattr(record,selector)))
                if parent is None: raise ImportMissingError('Exact parent ID not found; no automatic creation or reconciliation')
                if getattr(record,parent_field) is not None and getattr(record,parent_field)!=parent.id:
                    raise ImportIdentityError('Internal parent ID does not match platform identifier')
                if record.source!=Source.MANUAL and not record.source.value.startswith(parent.platform.value+'_'):
                    raise ImportIdentityError('Source does not match parent platform')
                values=record.model_dump(exclude={'platform',selector,'geography'})
                values[parent_field]=parent.id
                values['raw_payload']=sanitize(record.raw_payload if record.raw_payload is not None else record.model_dump(mode='json'),())
                row=model(**values);db.add(row);db.flush();rows[label].append(row.id)
                if label=='content':
                    for geo in record.geography:
                        db.add(ContentGeoSnapshot(content_snapshot_id=row.id,**geo.model_dump()))
        db.commit()
    except Exception:
        db.rollback();raise
    return rows
