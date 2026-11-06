#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
static int width=1920,height=1080;
static void fail(NSString *reason){fprintf(stderr,"%s\n",reason.UTF8String);exit(1);}
static CVPixelBufferRef buffer(NSDictionary *attrs){CVPixelBufferRef p=NULL;if(CVPixelBufferCreate(NULL,width,height,kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,(__bridge CFDictionaryRef)attrs,&p))fail(@"buffer allocation");return p;}
static BOOL transfer(CVPixelBufferRef p,BOOL write){CVPixelBufferLockFlags flags=write?kCVPixelBufferLock_ReadOnly:0;CVPixelBufferLockBaseAddress(p,flags);for(int plane=0;plane<2;plane++){unsigned char *base=CVPixelBufferGetBaseAddressOfPlane(p,plane);size_t stride=CVPixelBufferGetBytesPerRowOfPlane(p,plane);for(int y=0;y<(plane?height/2:height);y++){unsigned char *a=base+y*stride;if(write){if(fwrite(a,1,width,stdout)!=width)fail(@"output stream");}else if(fread(a,1,width,stdin)!=width){CVPixelBufferUnlockBaseAddress(p,flags);if(feof(stdin)&&plane==0&&y==0)return NO;fail(@"short input frame");}}}CVPixelBufferUnlockBaseAddress(p,flags);return YES;}
int main(int argc,char**argv){@autoreleasepool{
 if(argc<3)fail(@"usage: interpolate sourceFrames outputFrames [cuts.json]");
 long n=atol(argv[1]),out=atol(argv[2]);
 NSArray *cuts=argc>3?[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[3])] options:0 error:nil]:@[];
 NSSet *cutset=[NSSet setWithArray:cuts?:@[]];
 VTFrameRateConversionConfiguration *config=[[VTFrameRateConversionConfiguration alloc]initWithFrameWidth:width frameHeight:height usePrecomputedFlow:NO qualityPrioritization:VTFrameRateConversionConfigurationQualityPrioritizationQuality revision:VTFrameRateConversionConfiguration.defaultRevision];
 VTFrameProcessor *proc=[VTFrameProcessor new];NSError *error=nil;
 if(!config||![proc startSessionWithConfiguration:config error:&error])fail(error.description?:@"unsupported");
 CVPixelBufferRef a=buffer(config.sourcePixelBufferAttributes),b=buffer(config.sourcePixelBufferAttributes),m=buffer(config.destinationPixelBufferAttributes);
 if(!transfer(a,NO))fail(@"empty input");BOOL has=transfer(b,NO);long i=0;
 for(long k=0;k<out;k++){@autoreleasepool{
  // 50 -> 60 on the original clock. Never rescale the performance duration.
  long target=(k*5)/6;int remainder=(k*5)%6;
  while(i<target&&has){CVPixelBufferRef t=a;a=b;b=t;i++;has=transfer(b,NO);}
  if(!has||remainder==0||[cutset containsObject:@(i+1)]){transfer(a,YES);continue;}
  VTFrameProcessorFrame *left=[[VTFrameProcessorFrame alloc]initWithBuffer:a presentationTimeStamp:CMTimeMake(i,50)];
  VTFrameProcessorFrame *right=[[VTFrameProcessorFrame alloc]initWithBuffer:b presentationTimeStamp:CMTimeMake(i+1,50)];
  VTFrameProcessorFrame *mid=[[VTFrameProcessorFrame alloc]initWithBuffer:m presentationTimeStamp:CMTimeMake(k,60)];
  VTFrameRateConversionParameters *params=[[VTFrameRateConversionParameters alloc]initWithSourceFrame:left nextFrame:right opticalFlow:nil interpolationPhase:@[@(remainder/6.0)] submissionMode:VTFrameRateConversionParametersSubmissionModeRandom destinationFrames:@[mid]];
  error=nil;if(!params||![proc processWithParameters:params error:&error])fail(error.description?:@"interpolation failed");transfer(m,YES);
 }}
 fprintf(stderr,"Processed %ld source frames -> %ld output frames\n",n,out);
 [proc endSession];CVPixelBufferRelease(a);CVPixelBufferRelease(b);CVPixelBufferRelease(m);
}}
