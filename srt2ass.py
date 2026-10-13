import argparse
import pysubs2

if __name__ == "__main__":
    # python srt2ass.py -i ori_lyrics/apologize.srt -o lyrics/apologize.ass
    parser = argparse.ArgumentParser(description='将 srt 转换成 ass 格式')
    parser.add_argument('--input', '-i', help='srt input')
    parser.add_argument('--output', '-o', help='ass output')
    
    args = parser.parse_args()
    subs = pysubs2.load(args.input)
    subs.save(args.output)
