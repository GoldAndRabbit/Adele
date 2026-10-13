#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
from datetime import timedelta

def format_time(seconds):
    """将秒数格式化为ASS所需的时间格式 (HH:MM:SS.mmm)"""
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int(delta.microseconds / 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

def txt_to_ass(txt_file, ass_file, line_duration=2.0, interval=0.5):
    """
    将TXT歌词转换为ASS格式，忽略[]包裹的内容
    txt_file: TXT歌词文件路径
    ass_file: ASS输出文件路径
    line_duration: 每行歌词显示时长(秒)
    interval: 行间隔时长(秒)
    """
    try:
        # 读取TXT歌词并过滤[]包裹的内容
        with open(txt_file, 'r', encoding='utf-8') as f:
            lines = []
            for line in f:
                # 去除[]内的内容及前后空格
                processed_line = re.sub(r'\[.*?\]', '', line).strip()
                if processed_line:  # 只保留非空行
                    lines.append(processed_line)
        
        if not lines:
            print("错误：TXT文件中没有找到有效歌词内容")
            return
        
        # 生成ASS文件内容
        ass_content = "[Script Info]\n"
        ass_content += "; 由TXT转换为ASS的歌词文件（自动过滤[]内容）\n"
        ass_content += "Title: 转换后的歌词\n"
        ass_content += "Original Script: \n"
        ass_content += "ScriptType: v4.00+\n"
        ass_content += "WrapStyle: 0\n"
        ass_content += "Collisions: Normal\n"
        ass_content += "PlayResX: 1280\n"
        ass_content += "PlayResY: 720\n\n"
        
        ass_content += "[V4+ Styles]\n"
        ass_content += "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        ass_content += "Style: Default,Arial,24,&HFFFFFF&,&HFFFFFF&,&H000000&,&H00000000&,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
        
        ass_content += "[Events]\n"
        ass_content += "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        
        # 计算每行歌词的时间并生成事件
        current_time = 0.0
        for i, line in enumerate(lines):
            start_time = current_time
            end_time = current_time + line_duration
            
            # 格式化时间
            start_str = format_time(start_time)
            end_str = format_time(end_time)
            
            # 添加歌词事件
            ass_content += f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{line}\n"
            
            # 更新当前时间（加上间隔）
            current_time = end_time + interval
        
        # 写入ASS文件
        with open(ass_file, 'w', encoding='utf-8') as f:
            f.write(ass_content)
        
        print(f"转换完成！ASS文件已保存至: {os.path.abspath(ass_file)}")
    
    except Exception as e:
        print(f"转换过程中出错: {str(e)}")

if __name__ == "__main__":
    import argparse
    # python txt_to_ass.py countingstars.txt -o countingstars.ass
    # apologize.txt
    parser = argparse.ArgumentParser(description='将TXT歌词转换为ASS格式，忽略[]包裹的内容')
    parser.add_argument('txt_file', help='TXT歌词文件路径')
    parser.add_argument('--output', '-o', help='ASS输出文件路径，默认为输入文件加.ass后缀')
    parser.add_argument('--duration', '-d', type=float, default=1.0, help='每行歌词显示时长(秒)，默认为2.0秒')
    parser.add_argument('--interval', '-i', type=float, default=0.2, help='行间隔时长(秒)，默认为0.5秒')
    
    args = parser.parse_args()
    
    txt_file = args.txt_file
    ass_file = args.output if args.output else os.path.splitext(txt_file)[0] + '.ass'
    line_duration = args.duration
    interval = args.interval
    
    txt_to_ass(txt_file, ass_file, line_duration, interval)