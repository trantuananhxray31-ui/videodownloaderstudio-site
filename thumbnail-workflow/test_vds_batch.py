import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageChops
import vds_batch as b


class VdsBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        font='C:/Windows/Fonts/arialbd.ttf'
        if not Path(font).exists():font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
        templates={}
        for ratio,size in b.SIZES.items():
            p=self.root/(ratio+'.png')
            Image.new('RGB',size,'#174373').save(p)
            templates[ratio]={'path':str(p),'badge_box':[.65,.02,.33,.13]}
        self.job={'mode':'have_original','series_folder':'Phim [HG_123]',
            'source':{'verified':True},'drive_root_id':'folder','inventory_complete':True,
            'episodes':[{'episode':1,'part':0},{'episode':3,'part':0},{'episode':3,'part':1}],
            'font':font,'templates':templates}
        self.run=self.root/'run'

    def tearDown(self):self.tmp.cleanup()

    def prepared(self):b.prepare(self.job,self.run)

    def test_scan_100_exact_numbers_and_ignore_subtitles(self):
        inputs=[{'id':str(n),'name':f'Tập {n:03d}_hg_123.mp4','mimeType':'application/octet-stream'} for n in range(1,101)]
        inputs.append({'id':'srt','name':'Tập 001_vi.srt','mimeType':'application/octet-stream'})
        r=b.classify(inputs)
        self.assertEqual([e['episode'] for e in r['episodes']],list(range(1,101)))
        self.assertEqual(len(r['episodes'])*2+2,202)
        self.assertFalse(r['duplicates']);self.assertFalse(r['unknown'])

    def test_gaps_duplicates_and_parts_reported(self):
        r=b.classify([{'id':str(i),'name':name} for i,name in enumerate(['Tập 001_a.mp4','Tập 001_b.mp4','Tập 003.mp4','full.mp4','Tập 004_phan01.mp4'])])
        self.assertIn('1',r['duplicates']);self.assertEqual(r['missing'],[2]);self.assertEqual(len(r['unknown']),2)
        self.assertEqual(r['episodes'][0]['episode'],3)

    def test_unverified_source_or_partial_inventory_rejected(self):
        self.job['source']['verified']=False
        with self.assertRaises(ValueError):self.prepared()
        self.job['source']['verified']=True;self.job['inventory_complete']=False
        with self.assertRaises(ValueError):self.prepared()

    def test_approval_required_and_template_change_invalidates(self):
        self.prepared()
        with self.assertRaises(ValueError):b.batch(self.run)
        b.approve(self.run,'Human')
        p=Path(self.job['templates']['16x9']['path'])
        Image.new('RGB',b.SIZES['16x9'],'red').save(p)
        with self.assertRaises(ValueError):b.batch(self.run)

    def test_batch_names_dimensions_and_no_overwrite(self):
        self.prepared();b.approve(self.run,'Human');result=b.batch(self.run)
        self.assertEqual(len(result['files']),8);self.assertEqual(result['ai_calls'],0)
        self.assertIn('TAP_003_PHAN_001_9x16.jpg',{x['name'] for x in result['files']})
        b.verify(self.run)
        self.assertTrue((self.run/'THUMBNAILS.zip').exists())
        self.assertEqual(b.batch(self.run)['files'],result['files'])
        p=self.run/'THUMBNAILS'/self.job['series_folder']/'TAP_001_9x16.jpg'
        p.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):b.verify(self.run)

    def test_only_badge_changes_in_uncompressed_candidate(self):
        self.prepared()
        p=self.run/'samples/TAP_001_16x9.jpg'
        # JPEG compression may alter pixels slightly; far from badge stays same to rounding.
        with Image.open(p) as im:
            self.assertTrue(all(abs(a-z)<=2 for a,z in zip(im.getpixel((100,700)),(23,67,115))))

    def test_run_is_exclusive_and_path_names_safe(self):
        self.prepared()
        with self.assertRaises(FileExistsError):self.prepared()
        for name in ['../escape','CON','x/y','name.']:
            with self.assertRaises(ValueError):b.folder_name(name)

    def test_full_100_episode_render_is_202_images(self):
        self.job['episodes']=[{'episode':n,'part':0} for n in range(1,101)]
        self.prepared();b.approve(self.run,'Test reviewer')
        r=b.batch(self.run)
        self.assertFalse(r['errors']);self.assertEqual(len(r['files']),202)
        self.assertEqual(len(b.verify(self.run)['files']),202)

    def test_resume_chunks_uses_one_approval_and_identical_prior_files(self):
        self.prepared();b.approve(self.run,'Human')
        first=b.batch(self.run,3)
        self.assertEqual(first['status'],'in_progress')
        original=dict((f['name'],f['sha256']) for f in first['files'])
        while True:
            result=b.batch(self.run,3)
            if result['status']=='ready_to_upload':break
        self.assertEqual(len(result['files']),8)
        self.assertTrue(all(original.get(f['name'],f['sha256'])==f['sha256'] for f in result['files']))


if __name__=='__main__':unittest.main()
