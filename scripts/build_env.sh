
# 创建虚拟环境
# python3 -m venv nemo_env
python3.12 -m venv my_venv
source my_venv/bin/activate
# source nemo_env/bin/activate

brew install cmake libsndfile

pip instaall demucs
# 安装 NeMo 及其依赖
# python 环境需要 3.12.2
# pip install Cython
# # pip install huggingface_hub==0.19.4
# pip install torch torchvision torchaudio
# pip install huggingface_hub
# pip install opencc-python-reimplemented==0.1.6
# pip install "nemo_toolkit[all]"

# pip install "nemo_toolkit[all]" -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

