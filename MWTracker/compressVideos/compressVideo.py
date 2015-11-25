# -*- coding: utf-8 -*-
"""
Created on Thu Apr  2 13:19:58 2015

@author: ajaver
"""
import numpy as np
import cv2
import h5py
import os
import sys

from .readVideoffmpeg import readVideoffmpeg
from .readVideoHDF5 import readVideoHDF5
#from .imageDifferenceMask import imageDifferenceMask

from ..helperFunctions.timeCounterStr import timeCounterStr

DEFAULT_MASK_PARAM = {'min_area':100, 'max_area':5000, 'has_timestamp':True, 'thresh_block_size':61, 'thresh_C':15, 'dilation_size': 9}


def getROIMask(image,  min_area = DEFAULT_MASK_PARAM['min_area'], max_area = DEFAULT_MASK_PARAM['max_area'], 
    has_timestamp = DEFAULT_MASK_PARAM['has_timestamp'], thresh_block_size = DEFAULT_MASK_PARAM['thresh_block_size'], 
    thresh_C = DEFAULT_MASK_PARAM['thresh_C'], dilation_size = DEFAULT_MASK_PARAM['dilation_size']):
    '''
    Calculate a binary mask to mark areas where it is possible to find worms.
    Objects with less than min_area or more than max_area pixels are rejected.
    '''
    #Objects that touch the limit of the image are removed. I use -2 because openCV findCountours remove the border pixels
    IM_LIMX = image.shape[0]-2
    IM_LIMY = image.shape[1]-2
    
    if thresh_block_size%2==0:
        thresh_block_size+=1 #this value must be odd
    
    #adaptative threshold is the best way to find possible worms. I setup the parameters manually, they seems to work fine if there is no condensation in the sample
    mask = cv2.adaptiveThreshold(image,255,cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, thresh_block_size, thresh_C)
    #ret, mask = cv2.threshold(image, thresh_C, 255, cv2.THRESH_BINARY_INV)


    #find the contour of the connected objects (much faster than labeled images)
    _, contours, hierarchy = cv2.findContours(mask.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    
    #find good contours: between max_area and min_area, and do not touch the image border
    goodIndex = []
    for ii, contour in enumerate(contours):
        if np.all(contour!=1) and np.all(contour[:,:,0] !=  IM_LIMX)\
        and np.all(contour[:,:,1] != IM_LIMY):
            area = cv2.contourArea(contour)
            if (area>=min_area) and (area<=max_area):
                goodIndex.append(ii)
    
    #typically there are more bad contours therefore it is cheaper to draw only the valid contours
    mask = np.zeros(image.shape, dtype=image.dtype)
    for ii in goodIndex:
        cv2.drawContours(mask, contours, ii, 1, cv2.FILLED)
    
    #drawContours left an extra line if the blob touches the border. It is necessary to remove it
    mask[0,:] = 0; mask[:,0] = 0; mask[-1,:] = 0; mask[:,-1]=0;
    
    #dilate the elements to increase the ROI, in case we are missing something important
    struct_element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilation_size,dilation_size)) 
    mask = cv2.dilate(mask, struct_element, iterations = 3)
    
    if has_timestamp:
        #the gecko images have a time stamp in the image border
        cv2.rectangle(mask, (0,0), (479,15), 1, thickness=-1) 

    return mask


READER_TYPE = {'OPENCV':0, 'FFMPEG_CMD':1, 'HDF5':2};
def selectVideoReader(video_file):
    #open video to read
    isHDF5video = video_file[-5:] == '.hdf5';
    isMJPGvideo = video_file[-5:] == '.mjpg';

    if isHDF5video:
        #use tables to read hdf5 with lz4 compression generated by the Gecko plugin
        vid = readVideoHDF5(video_file);
        im_height = vid.height;
        im_width = vid.width;
        reader_type = READER_TYPE['HDF5']

    elif isMJPGvideo:
        #use previous ffmpeg that is more compatible with the Gecko MJPG format
        vid = readVideoffmpeg(video_file);
        im_height = vid.height;
        im_width = vid.width;
        reader_type = READER_TYPE['FFMPEG_CMD']
    else:
        #use opencv VideoCapture
        vid = cv2.VideoCapture(video_file);
        im_width= vid.get(cv2.CAP_PROP_FRAME_WIDTH)
        im_height= vid.get(cv2.CAP_PROP_FRAME_HEIGHT)
        #sometimes video capture seems to give the wrong dimenssions read the firest image and try again
        ret, image = vid.read() #get video frame, stop program when no frame is retrive (end of file)
        if ret:
            im_height, im_width, _ = image.shape
            vid.release()
            vid = cv2.VideoCapture(video_file);
        reader_type = READER_TYPE['OPENCV']

    return vid, im_width, im_height, reader_type


def compressVideo(video_file, masked_image_file, buffer_size = 25, \
save_full_interval = 5000, max_frame = 1e32, 
expected_frames = 15000, mask_param = DEFAULT_MASK_PARAM):

    '''
    Compressed video in "video_file" by selecting ROI and making the rest of 
    the image zero (creating a large amount of redundant data)
    the final images are saving in the file given by "masked_image_file" 
    as hdf5 with gzip compression
    To reduce the processing load buffer_size images are collected, and a minimum filter 
    applied over the stack. In this way the pixels corresponding to the worms are 
    preserved as black pixels in the min-average image, and only in this 
     image the the binary mask with possible worms is calculated.

     MAX_N_PROCESSES -- number of processes using during image processing, if -1, this value is set to the number of cpu is using
     save_full_interval --  Full frame is saved every 'save_full_interval' in '/full_data'
     max_frame -- maximum number of frames to be analyzed. Set this value to a large value to compress all the video    
     status_queue -- queue were the status is sended. Only used in multiprocessing case 
     base_name -- 
    '''
    
    #processes identifier.
    base_name = masked_image_file.rpartition('.')[0].rpartition(os.sep)[-1]
    
    #select the video reader class according to the file type. 
    vid, im_width, im_height, reader_type = selectVideoReader(video_file)
    
    if im_width == 0 or im_height == 0:
        raise(RuntimeError('Cannot read the video file correctly. Dimensions w=%i h=%i' % (im_width, im_height)))

    #open hdf5 to store the processed data
    mask_fid = h5py.File(masked_image_file, "w");
    #open node to store the compressed (masked) data
    mask_dataset = mask_fid.create_dataset("/mask", (expected_frames, im_height,im_width), 
                                    dtype = "u1", maxshape = (None, im_height,im_width), 
                                    chunks = (1, im_height,im_width),
                                    compression="gzip", 
                                    compression_opts=4,
                                    shuffle=True, fletcher32=True);

    #labels to make the group compatible with the standard image definition in hdf5
    mask_dataset.attrs["CLASS"] = np.string_("IMAGE")
    mask_dataset.attrs["IMAGE_SUBCLASS"] = np.string_("IMAGE_GRAYSCALE")
    mask_dataset.attrs["IMAGE_WHITE_IS_ZERO"] = np.array(0, dtype="uint8")
    mask_dataset.attrs["DISPLAY_ORIGIN"] = np.string_("UL") # not rotated
    mask_dataset.attrs["IMAGE_VERSION"] = np.string_("1.2")

    #flag to store the parameters using in the mask calculation
    for key in DEFAULT_MASK_PARAM:
        if key in mask_param:
            mask_dataset.attrs[key] = int(mask_param[key])
        else:
            mask_dataset.attrs[key] = int(DEFAULT_MASK_PARAM[key])
    
    #flag to indicate that the conversion finished succesfully
    mask_dataset.attrs['has_finished'] = 0

    #full frames are saved in "/full_data" every save_full_interval frames
    full_dataset = mask_fid.create_dataset("/full_data", (expected_frames//save_full_interval, im_height,im_width), 
                                    dtype = "u1", maxshape = (None, im_height,im_width), 
                                    chunks = (1, im_height,im_width),
                                    compression="gzip", 
                                    compression_opts=4,
                                    shuffle=True, fletcher32=True);
    full_dataset.attrs['save_interval'] = save_full_interval
    
    #labels to make the group compatible with the standard image definition in hdf5
    full_dataset.attrs["CLASS"] = np.string_("IMAGE")
    full_dataset.attrs["IMAGE_SUBCLASS"] = np.string_("IMAGE_GRAYSCALE")
    full_dataset.attrs["IMAGE_WHITE_IS_ZERO"] = np.array(0, dtype="uint8")
    full_dataset.attrs["DISPLAY_ORIGIN"] = np.string_("UL") # not rotated
    full_dataset.attrs["IMAGE_VERSION"] = np.string_("1.2")



    #im_diff_set = mask_fid.create_dataset('/im_diff', (expected_frames,), 
    #                                      dtype = 'f4', maxshape = (None,), 
    #                                    chunks = True, compression = "gzip", compression_opts=4, shuffle = True, fletcher32=True)
    
    #intialize frame number
    frame_number = 0;
    full_frame_number = 0;
    image_prev = np.zeros([]);
    
    vid_frame_pos = []
    vid_time_pos = []

    #initialize timers
    progressTime = timeCounterStr('Compressing video.');

    while frame_number < max_frame:
        if reader_type == READER_TYPE['OPENCV']:
            vid_frame_pos.append(int(vid.get(cv2.CAP_PROP_POS_FRAMES)))
            vid_time_pos.append(vid.get(cv2.CAP_PROP_POS_MSEC))

        ret, image = vid.read() #get video frame, stop program when no frame is retrive (end of file)
        if ret == 0:
            break
        
        if image.ndim==3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        
        frame_number += 1;
        
        #import matplotlib.pylab as plt
        #plt.figure()
        #plt.imshow(image)
        
        #Resize mask array every 1000 frames (doing this every frame does not impact much the performance)
        if mask_dataset.shape[0] <= frame_number + 1:
            mask_dataset.resize(frame_number + 1000, axis=0); 
            #im_diff_set.resize(frame_number + 1000, axis=0); 
        #Add a full frame every save_full_interval
        if frame_number % save_full_interval == 1:
            if full_dataset.shape[0] <= full_frame_number:
                full_dataset.resize(full_frame_number+1, axis=0); 
                assert(frame_number//save_full_interval == full_frame_number) #just to be sure that the index we are saving in is what we what we are expecting
            full_dataset[full_frame_number,:,:] = image.copy()
            full_frame_number += 1;

        
        ind_buff = (frame_number-1) % buffer_size #buffer index
        
        #initialize the buffer when the index correspond to 0
        if ind_buff == 0:
            Ibuff = np.zeros((buffer_size, im_height, im_width), dtype = np.uint8)

        #add image to the buffer
        Ibuff[ind_buff, :, :] = image.copy()
        
        if ind_buff == buffer_size-1:
            #calculate the mask only when the buffer is full
            mask = getROIMask(np.min(Ibuff, axis=0), **mask_param)
            
            #mask all the images in the buffer
            Ibuff *= mask
            
            #add buffer to the hdf5 file
            mask_dataset[(frame_number-buffer_size):frame_number,:,:] = Ibuff
            
            
            #calculate difference between image (it's usefull to indentified corrupted frames)
            if mask_param['has_timestamp']:
                #remove timestamp before calculation
                Ibuff[:,0:15,0:479] = 0; 
            
            #for ii in range(Ibuff.shape[0]):
            #    if image_prev.shape and ii == 0:
            #        dd = imageDifferenceMask(Ibuff[ii,:,:],image_prev)
            #    else:
            #        dd = imageDifferenceMask(Ibuff[ii,:,:],Ibuff[ii-1,:,:])
            #    
            #    im_diff_set[frame_number-buffer_size+ii] = dd
                
            #image_prev = Ibuff[-1,:,:].copy();  

        if frame_number%500 == 0:
            #calculate the progress and put it in a string
            progress_str = progressTime.getStr(frame_number)
            print(base_name + ' ' + progress_str);
            sys.stdout.flush()
        
    
    if mask_dataset.shape[0] != frame_number:
        mask_dataset.resize(frame_number, axis=0);
        #im_diff_set.resize(frame_number, axis=0);
        
    if full_dataset.shape[0] != full_frame_number:
        full_dataset.resize(full_frame_number, axis=0);
    
    mask_dataset.attrs['has_finished'] = 1
        
    #close the video
    vid.release() 

    #if it is not opencv the timestamp from the vid reader
    if reader_type != READER_TYPE['OPENCV']:
        vid_frame_pos = vid.vid_frame_pos
        vid_time_pos = vid.vid_time_pos

    #save time stamp
    mask_fid.create_dataset("/vid_frame_pos", data = np.asarray(vid_frame_pos));
    mask_fid.create_dataset("/vid_time_pos", data = np.asarray(vid_time_pos));


    #close the hdf5 files
    mask_fid.close()
    print(base_name + ' Compressed video done.');
    sys.stdout.flush()

if __name__ == '__main__':
    video_file = '/Users/ajaver/Desktop/Gecko_compressed/Raw_Video/Capture_Ch1_11052015_195105.mjpg'
    masked_image_file = '/Users/ajaver/Desktop/Gecko_compressed/Masked_Videos/20150511/Capture_Ch1_11052015_195105.hdf5'
    compressVideo(video_file, masked_image_file, useVideoCapture=False)
