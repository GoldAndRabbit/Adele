exec(open('work/grammy-ts-review/speed_check.py').read().split('x=audio')[0])
source=Path('/Volumes/harddisk_5T/thunder_downloads/The 56th Grammy Awards 2014.ts/The 56th Grammy Awards 2014.ts')
x=audio(source,1248,30)
for t in [3,8,14,20,28]:
 y=audio(src,t,2);z=correlate(x,y,mode='valid',method='fft');pw=np.r_[0.,np.cumsum(x*x)];z/=np.sqrt(np.maximum((pw[len(y):]-pw[:-len(y)])*(y*y).sum(),1e-10));i=abs(z).argmax()
 print(t,round(float(abs(z[i])),3),round(1248+i/8000-t,3),flush=True)
