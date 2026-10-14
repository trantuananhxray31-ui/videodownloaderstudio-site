import unittest
from composio_drive import Drive, unwrap


class DriveTests(unittest.TestCase):
    def test_empty_page_with_next_token_is_not_end(self):
        calls=[]
        def runner(slug,args,account):
            calls.append((slug,args,account))
            page={'files':[],'nextPageToken':'opaque+token'} if len(calls)==1 else {'files':[{'id':'a','name':'image.jpg'}]}
            return {'data':{'successful':True,'data':page}},None
        result=Drive(runner).files('parent')
        self.assertEqual(result[0]['id'],'a')
        self.assertEqual(calls[1][1]['pageToken'],'opaque+token')
        self.assertEqual(calls[0][2],'BRU Drive xray31')

    def test_duplicate_folder_never_created(self):
        def runner(slug,args,account):
            self.assertEqual(slug,'GOOGLEDRIVE_FIND_FILE')
            return {'data':{'files':[{'id':'a','name':'Phim'},{'id':'b','name':'Phim'}]}},None
        with self.assertRaises(ValueError):Drive(runner).folder('parent','Phim')

    def test_connector_error_stops_without_retry(self):
        calls=[]
        def runner(slug,args,account):calls.append(slug);return {},'timeout'
        with self.assertRaises(RuntimeError):Drive(runner).call('GOOGLEDRIVE_UPLOAD_FROM_URL',{})
        self.assertEqual(len(calls),1)

    def test_error_envelope_rejected(self):
        with self.assertRaises(ValueError):unwrap({'data':{'successful':False,'error':'denied'}})


if __name__=='__main__':unittest.main()
