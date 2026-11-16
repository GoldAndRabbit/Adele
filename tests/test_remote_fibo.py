import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.remote_fibo_worker import main
from workflow.live.paths import write_json


class RemoteFiboTests(unittest.TestCase):
    def test_auxiliary_face_reference_is_verified_before_model_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);(job/'reference.png').write_bytes(b'source');(job/'identity-1.png').write_bytes(b'changed')
            write_json(job/'request.json',{'input_sha256':hashlib.sha256(b'source').hexdigest(),
                'images':{'reference.png':hashlib.sha256(b'source').hexdigest(),
                          'identity-1.png':hashlib.sha256(b'original crop').hexdigest()}})
            with patch('sys.argv',['worker',str(job/'request.json')]), \
                 patch('workflow.remote_fibo_worker.subprocess.run') as generate:
                with self.assertRaisesRegex(ValueError,'auxiliary'):
                    main()
                generate.assert_not_called()

    def test_multiple_references_keep_their_order_and_remote_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);job=home/'job';job.mkdir();images={}
            for name in ['reference.png','identity-1.png']:
                (job/name).write_bytes(name.encode());images[name]=hashlib.sha256(name.encode()).hexdigest()
            args=['--model','local','--image-paths','local/ref.png','local/face.png',
                  '--prompt','one singer','--width','1024','--height','576','--output','local/master.png']
            write_json(job/'request.json',{'input_sha256':images['reference.png'],'images':images,'args':args})
            def generate(*args,**kwargs):
                (job/'master.png').write_bytes(b'generated');(job/'master.metadata.json').write_bytes(b'{}')
            with patch('workflow.remote_fibo_worker.Path.home',return_value=home), \
                 patch('sys.argv',['worker',str(job/'request.json')]), \
                 patch('workflow.remote_fibo_worker.subprocess.run',side_effect=generate) as call:
                main();argv=call.call_args.args[0]
            start=argv.index('--image-paths')+1;end=argv.index('--prompt')
            self.assertEqual(argv[start:end],[str((job/'reference.png').resolve()),str((job/'identity-1.png').resolve())])
            self.assertEqual(argv[argv.index('--width')+1],'768')
            self.assertEqual(argv[-2:],['--quantize','4'])

    def test_completed_remote_job_is_returned_without_another_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp);job = home/'job';job.mkdir()
            (job/'reference.png').write_bytes(b'source')
            write_json(job/'request.json', {'input_sha256':hashlib.sha256(b'source').hexdigest()})
            hashes = {}
            for name in ['master.png', 'master.metadata.json']:
                (job/name).write_bytes(b'finished')
                hashes[name] = hashlib.sha256(b'finished').hexdigest()
            write_json(job/'success.json', hashes)
            with patch('workflow.remote_fibo_worker.Path.home',return_value=home), \
                 patch('sys.argv',['worker',str(job/'request.json')]), \
                 patch('workflow.remote_fibo_worker.subprocess.run') as generate:
                main()
                generate.assert_not_called()

    def test_changed_reference_cannot_use_a_transferred_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp);(job/'reference.png').write_bytes(b'changed')
            write_json(job/'request.json', {'input_sha256':hashlib.sha256(b'original').hexdigest()})
            with patch('sys.argv',['worker',str(job/'request.json')]), \
                 patch('workflow.remote_fibo_worker.subprocess.run') as generate:
                with self.assertRaisesRegex(ValueError,'checksum'):
                    main()
                generate.assert_not_called()
