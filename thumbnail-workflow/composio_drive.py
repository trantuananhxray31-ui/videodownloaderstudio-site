"""Use ONLY inside @1 Workbench with injected run_composio_tool/upload_local_file."""
from pathlib import Path
import hashlib
import json
import vds_batch


def unwrap(value):
    for _ in range(5):
        if not isinstance(value, dict):raise ValueError('Unexpected connector output')
        if value.get('successful') is False or value.get('success') is False:
            raise ValueError('Connector action failed')
        if 'data' not in value:return value
        value=value['data']
    raise ValueError('Connector envelope nesting not recognized')


class Drive:
    def __init__(self, runner, account='BRU Drive xray31'):
        self.runner=runner
        self.account=account

    def call(self, slug, args):
        response,error=self.runner(slug,args,account=self.account)
        if error:raise RuntimeError(f'{slug} failed; do not retry a write blindly')
        return unwrap(response)

    def metadata(self, file_id):
        return self.call('GOOGLEDRIVE_GET_FILE_METADATA', {'fileId':file_id,
            'fields':'id,name,mimeType,parents,md5Checksum,size,trashed,capabilities(canAddChildren)'})

    def files(self, parent):
        result=[]
        token=None
        seen=set()
        while True:
            args={'folder_id':parent,'q':'trashed = false','pageSize':1000,
                  'fields':'nextPageToken,incompleteSearch,files(id,name,mimeType,parents,md5Checksum,size)'}
            if token:args['pageToken']=token
            page=self.call('GOOGLEDRIVE_FIND_FILE',args)
            if page.get('incompleteSearch'):raise ValueError('Incomplete Drive search')
            if 'files' not in page:raise ValueError('Unexpected file listing schema')
            result.extend(page['files'])
            token=page.get('nextPageToken')
            if not token:return result
            if token in seen:raise ValueError('Repeated pagination token')
            seen.add(token)

    def folder(self, parent, name):
        matches=[f for f in self.files(parent) if f['name']==name]
        if len(matches)>1:raise ValueError('Ambiguous destination folder')
        if matches:
            if matches[0]['mimeType']!='application/vnd.google-apps.folder':
                raise ValueError('Destination name is not a folder')
            return matches[0]['id']
        created=self.call('GOOGLEDRIVE_CREATE_FOLDER', {'name':name,'parent_id':parent})
        meta=self.metadata(created['id'])
        if parent not in meta.get('parents',[]):raise ValueError('Folder created in wrong parent')
        return created['id']

    def scan_one_film(self, source_folder_id):
        """Read metadata only; checkpoint the returned inventory after each film."""
        root=self.metadata(source_folder_id)
        if root.get('mimeType')!='application/vnd.google-apps.folder':raise ValueError('Not a source folder')
        queue=[source_folder_id]
        visited=set()
        files=[]
        while queue:
            parent=queue.pop(0)
            if parent in visited:continue
            visited.add(parent)
            for item in self.files(parent):
                if item['mimeType']=='application/vnd.google-apps.folder':
                    if not item['name'].startswith(('.', '_')):queue.append(item['id'])
                else:files.append(item)
        return {'source_folder_id':source_folder_id,'source_name':root['name'],
                'inventory_complete':True,'files':files,'classification':vds_batch.classify(files)}

    def publish(self, run, uploader, limit=20):
        """Single uploader only. Readbacks and immutable receipts support safe resume."""
        run=Path(run)
        result=vds_batch.verify(run)
        job=vds_batch.load(run/'job.json')
        root_meta=self.metadata(job['drive_root_id'])
        if root_meta.get('mimeType')!='application/vnd.google-apps.folder' or root_meta.get('name')!='THUMBNAILS':
            raise ValueError('Wrong THUMBNAILS root')
        target=self.folder(job['drive_root_id'],job['series_folder'])
        existing=self.files(target)
        pending=[]
        for f in result['files']:
            same=[x for x in existing if x['name']==f['name']]
            if same and (len(same)!=1 or same[0].get('md5Checksum')!=f['md5']):
                raise FileExistsError('Existing thumbnail conflict: '+f['name'])
            if not same:pending.append(f)
        receipts=run/'drive-receipts'
        receipts.mkdir(exist_ok=True)
        uploaded=[]
        for f in pending[:limit]:
            if any(x['name']==f['name'] for x in self.files(target)):
                raise FileExistsError('Destination changed during upload')
            local=run/'THUMBNAILS'/job['series_folder']/f['name']
            artifact,error=uploader(str(local))
            if error:raise RuntimeError('Could not materialize generated JPEG')
            artifact=unwrap(artifact)
            url=artifact.get('s3_url') or artifact.get('url')
            if not url or not url.startswith('https://'):raise ValueError('Missing HTTPS file artifact URL')
            # Create is never retried automatically: a timeout may already have created the file.
            created=self.call('GOOGLEDRIVE_UPLOAD_FROM_URL', {'source_url':url,'name':f['name'],
                'mime_type':'image/jpeg','parent_folder_id':target,'supports_all_drives':True})
            if 'id' not in created:raise ValueError('Upload response ID unavailable; inspect folder before retry')
            meta=self.metadata(created['id'])
            if meta.get('name')!=f['name'] or target not in meta.get('parents',[]) or meta.get('md5Checksum')!=f['md5']:
                raise ValueError('Upload readback failed; inspect created file, do not overwrite')
            receipt=receipts/(f['name']+'.json')
            if not receipt.exists():vds_batch.save(receipt, {'id':created['id'],'name':f['name'],'md5':f['md5'],'parent':target})
            uploaded.append(created['id'])
        return {'uploaded':len(uploaded),'remaining':max(0,len(pending)-len(uploaded)),
                'series_folder_id':target,'status':'complete' if len(pending)<=limit else 'in_progress'}
