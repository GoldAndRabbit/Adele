"""Run the installed MFLUX CLI after materializing disk-backed weights.

Cold model files on the external drive can stall the first Metal command long
enough to time out. Evaluate each weight before starting inference so disk I/O
is completed outside that command; model parameters and sampling stay intact.
Run this entry point with the local MFLUX virtual environment's Python.
"""


def main():
    import os
    import mlx.core as mx
    from mlx.utils import tree_flatten
    from mflux.models.fibo2.cli.fibo2_edit_generate import Fibo2EditCommand
    from mflux.models.fibo2.cli.fibo2_edit_generate import main as generate
    area = os.environ.get('FIBO_REFERENCE_AREA')
    if area:
        from mflux.models.fibo2.variants.edit.fibo2_edit_images import Fibo2EditImages
        Fibo2EditImages.AREA = int(area)
        from mflux.utils.image_util import ImageUtil
        original_prepare = Fibo2EditImages.prepare

        def composition_and_detail(image_paths, width=None, height=None, mask_path=None):
            if len(image_paths) == 1 or mask_path is not None:
                return original_prepare(image_paths,width,height,mask_path)
            images = [ImageUtil.load_image(path) for path in image_paths]
            width,height = Fibo2EditImages._result_size(images[0].width/images[0].height,width,height)
            width,height = 16*(width//16),16*(height//16)
            # Keep the full scene dominant. Equally large face and scene
            # conditioning tends to turn a wide shot into an unwanted closeup.
            sizes=[(width,height)]
            previous_area=Fibo2EditImages.AREA
            try:
                Fibo2EditImages.AREA=max(65536,int(area)//4)
                sizes += [Fibo2EditImages.trained_size(im.width/im.height) for im in images[1:]]
            finally:
                Fibo2EditImages.AREA=previous_area
            crops=[Fibo2EditImages._resize_and_crop(im,w,h) for im,(w,h) in zip(images,sizes)]
            text=[]
            for crop in crops:
                small=crop.copy();small.thumbnail((768,768));text.append(small)
            return crops,text,(width,height)
        Fibo2EditImages.prepare=staticmethod(composition_and_detail)

    load = Fibo2EditCommand.load

    def preload(args):
        # The 16 GiB worker quantizes on CPU before allocating Metal buffers.
        # Evaluating one parameter at a time avoids materializing the bf16
        # checkpoint and its quantized copy together on the GPU.
        cpu_load = os.environ.get('FIBO_PRELOAD_DEVICE') == 'cpu'
        if cpu_load:
            mx.set_default_device(mx.cpu)
        model = load(args)
        for name in ('vae', 'transformer', 'text_encoder'):
            weights = tree_flatten(getattr(model, name).parameters())
            print(f'Preloading {name}: {len(weights)} weights', flush=True)
            for index, (_, value) in enumerate(weights):
                mx.eval(value)
                if index % 100 == 0:
                    print(f'Loaded {name}: {index}/{len(weights)}', flush=True)
        if cpu_load:
            mx.clear_cache()
            mx.set_default_device(mx.gpu)
            mx.set_cache_limit(128 * 1024**2)
            # Fail within a bounded Metal budget instead of exhausting the
            # 16 GiB machine and entering unbounded swap.
            mx.set_memory_limit(12 * 1024**3)
        return model

    Fibo2EditCommand.load = staticmethod(preload)
    try:
        generate()
    finally:
        Fibo2EditCommand.load = staticmethod(load)


if __name__ == '__main__':
    main()
