# -*- coding: utf-8 -*-
"""
Created on Wed May 20 12:46:20 2015

@author: ajaver
"""

import h5py
import matplotlib.pylab as plt
import cv2
import numpy as np
import time
from scipy.interpolate import interp1d, RectBivariateSpline, interp2d

from cleanWorm import cleanWorm, circSmooth, extremaPeaksCircDist
from linearSkeleton import linearSkeleton
from segWorm_cython import circComputeChainCodeLengths
from getHeadTail import getHeadTail, rollHead2FirstIndex

#wrappers around C functions
from circCurvature import circCurvature 
from curvspace import curvspace

def contour2Skeleton(contour, resampling_N=50):
#%%    
    if type(contour) != np.ndarray or contour.ndim != 2 or contour.shape[1] !=2:
        err_msg =  'Contour must be a Nx2 numpy array'
        return 7*[np.zeros(0)]+[err_msg]
    
    if contour.dtype != np.double:
        contour = contour.astype(np.double)
    
    #% The worm is roughly divided into 24 segments of musculature (i.e., hinges
    #% that represent degrees of freedom) on each side. Therefore, 48 segments
    #% around a 2-D contour.
    #% Note: "In C. elegans the 95 rhomboid-shaped body wall muscle cells are
    #% arranged as staggered pairs in four longitudinal bundles located in four
    #% quadrants. Three of these bundles (DL, DR, VR) contain 24 cells each,
    #% whereas VL bundle contains 23 cells." - www.wormatlas.org
    ske_worm_segments = 24.;
    cnt_worm_segments = 2. * ske_worm_segments;

    
    contour = cleanWorm(contour, cnt_worm_segments) #this part does not really seem to be useful
    
    #% The contour is too small.
    if contour.shape[0] < cnt_worm_segments:
        err_msg =  'Contour is too small'
        return 7*[np.zeros(0)]+[err_msg]
    
    #% Compute the contour's local high/low-frequency curvature.
    #% Note: worm body muscles are arranged and innervated as staggered pairs.
    #% Therefore, 2 segments have one theoretical degree of freedom (i.e. one
    #% approximation of a hinge). In the head, muscles are innervated
    #% individually. Therefore, we sample the worm head's curvature at twice the
    #% frequency of its body.
    #% Note 2: we ignore Nyquist sampling theorem (sampling at twice the
    #% frequency) since the worm's cuticle constrains its mobility and practical
    #% degrees of freedom.

    cnt_chain_code_len = circComputeChainCodeLengths(contour);
    worm_seg_length = (cnt_chain_code_len[0] + cnt_chain_code_len[-1]) / cnt_worm_segments;
    
    edge_len_hi_freq = worm_seg_length;
    cnt_ang_hi_freq = circCurvature(contour, edge_len_hi_freq, cnt_chain_code_len);
    
    edge_len_low_freq = 2 * edge_len_hi_freq;
    cnt_ang_low_freq = circCurvature(contour, edge_len_low_freq, cnt_chain_code_len);
    
    #% Blur the contour's local high-frequency curvature.
    #% Note: on a small scale, noise causes contour imperfections that shift an
    #% angle from its correct location. Therefore, blurring angles by averaging
    #% them with their neighbors can localize them better.
    worm_seg_size = contour.shape[0] / cnt_worm_segments;
    blur_size_hi_freq = np.ceil(worm_seg_size / 2);
    cnt_ang_hi_freq = circSmooth(cnt_ang_hi_freq, blur_size_hi_freq)
        
    #% Compute the contour's local high/low-frequency curvature maxima.
    maxima_hi_freq, maxima_hi_freq_ind = \
    extremaPeaksCircDist(1, cnt_ang_hi_freq, edge_len_hi_freq, cnt_chain_code_len)
    
    maxima_low_freq, maxima_low_freq_ind = \
    extremaPeaksCircDist(1, cnt_ang_low_freq, edge_len_low_freq, cnt_chain_code_len)

    head_ind, tail_ind, err_msg = \
    getHeadTail(cnt_ang_low_freq, maxima_low_freq_ind, cnt_ang_hi_freq, maxima_hi_freq_ind, cnt_chain_code_len)
    
    if err_msg:
        return 7*[np.zeros(0)]+[err_msg]
    
    #change arrays so the head correspond to the first position
    head_ind, tail_ind, contour, cnt_chain_code_len, cnt_ang_low_freq, maxima_low_freq_ind = \
    rollHead2FirstIndex(head_ind, tail_ind, contour, cnt_chain_code_len, cnt_ang_low_freq, maxima_low_freq_ind)

    #% Compute the contour's local low-frequency curvature minima.
    minima_low_freq, minima_low_freq_ind = \
    extremaPeaksCircDist(-1, cnt_ang_low_freq, edge_len_low_freq, cnt_chain_code_len);
#%%
    #% Compute the worm's skeleton.
    skeleton, cnt_widths = linearSkeleton(head_ind, tail_ind, minima_low_freq, minima_low_freq_ind, \
        maxima_low_freq, maxima_low_freq_ind, contour.copy(), worm_seg_length, cnt_chain_code_len);

    #The head must be in position 0    
    assert head_ind == 0
    
    # Get the contour for each side.
    cnt_side1 = contour[:tail_ind+1, :].copy()
    cnt_side2 = np.vstack([contour[0,:], contour[:tail_ind-1:-1,:]])
    
    assert np.all(cnt_side1[0] == cnt_side2[0])
    assert np.all(cnt_side1[-1] == cnt_side2[-1])
    assert np.all(skeleton[-1] == cnt_side1[-1])
    assert np.all(skeleton[0] == cnt_side2[0])

    
    #resample data
    skeleton, ske_len = curvspace(skeleton, resampling_N)
    cnt_side1, cnt_side1_len = curvspace(cnt_side1, resampling_N)
    cnt_side2, cnt_side2_len = curvspace(cnt_side2, resampling_N)
    
    f = interp1d(np.arange(cnt_widths.size), cnt_widths)
    x = np.linspace(0,cnt_widths.size-1, resampling_N)
    cnt_widths = f(x);
#%%    
    return skeleton, cnt_side1, cnt_side2, cnt_widths, ske_len, cnt_side1_len, cnt_side2_len,  ''

def binaryMask2Contour(worm_mask, min_mask_area=50, roi_center_x = -1, roi_center_y = -1, pick_center = True):
    if roi_center_x < 1:
        roi_center_x = (worm_mask.shape[1]-1)/2.
    if roi_center_y < 1:
        roi_center_y = (worm_mask.shape[0]-1)/2.
    
    #select only one contour in the binary mask
    #get contour
    _,contour, _ = cv2.findContours(worm_mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if len(contour) == 1:
        contour = np.squeeze(contour[0])
    elif len(contour)>1:
    #clean mask if there is more than one contour
        #select the largest area  object
        cnt_areas = [cv2.contourArea(cnt) for cnt in contour]
        
        #filter only contours with areas larger than min_mask_area
        cnt_tuple = [(contour[ii], cnt_area) for ii, cnt_area in enumerate(cnt_areas) if cnt_area>min_mask_area]
        if not cnt_tuple:
            return np.zeros([])
        contour, cnt_areas = zip(*cnt_tuple)
        
        if pick_center:
            #In the multiworm tracker the worm should be in the center of the ROI
            min_dist_center = np.inf;
            valid_ind = -1
            for ii, cnt in enumerate(contour):
                mm = cv2.moments(cnt)
                cm_x = mm['m10']/mm['m00']
                cm_y = mm['m01']/mm['m00']
                dist_center = (cm_x-roi_center_x)**2 + (cm_y-roi_center_y)**2
                if min_dist_center > dist_center:
                    min_dist_center = dist_center
                    valid_ind = ii
        else: 
            #select the largest area  object
            valid_ind = np.argmax(cnt_areas)
        
        #return the correct contour if there is a valid number
        contour = np.squeeze(contour[valid_ind])
    else:
        contour = np.zeros([])
    return contour.astype(np.double)


def orientWorm(skeleton, prev_skeleton, cnt_side1, cnt_side1_len, cnt_side2, cnt_side2_len, cnt_widths):
    if skeleton.size == 0:
        return skeleton, cnt_side1, cnt_side1_len, cnt_side2, cnt_side2_len, cnt_widths
    
    #orient head tail with respect to hte previous worm
    if prev_skeleton.size > 0:
        dist2prev_head = np.sum((skeleton[0:3,:]-prev_skeleton[0:3,:])**2)
        dist2prev_tail = np.sum((skeleton[0:3,:]-prev_skeleton[-3:,:])**2)
        
        if dist2prev_head > dist2prev_tail: 
            #the skeleton is switched
            skeleton = skeleton[::-1,:]
            cnt_widths = cnt_widths[::-1]
            cnt_side1 = cnt_side1[::-1,:]
            cnt_side2 = cnt_side2[::-1,:]
        
    #make sure the contours are in the clockwise direction
    #x1y2 - x2y1(http://mathworld.wolfram.com/PolygonArea.html)
    contour = np.vstack((cnt_side1, cnt_side2[::-1,:])) 
    signed_area = np.sum(contour[:-1,0]*contour[1:,1]-contour[1:,0]*contour[:-1,1])/2
    if signed_area<0:
        cnt_side1, cnt_side2 = cnt_side2, cnt_side1
        cnt_side1_len, cnt_side2_len = cnt_side2_len, cnt_side1_len
    
    return skeleton, cnt_side1, cnt_side1_len, cnt_side2, cnt_side2_len, cnt_widths


def angleSmoothed(x, y, window_size):
    #given a series of x and y coordinates over time, calculates the angle
    #between each tangent vector over a given window making up the skeleton
    #and the x-axis.
    #arrays to build up and export
    dX = x[:-window_size] - x[window_size:];
    dY = y[:-window_size] - y[window_size:];
    
    #calculate angles
    skel_angles = np.arctan2(dY, dX)
    
    
    #%repeat final angle to make array the same length as skelX and skelY
    skel_angles = np.lib.pad(skel_angles, (window_size//2, window_size//2), 'edge')
    return skel_angles;

def getStraightenWormInt(worm_img, skeleton, half_width = -1, cnt_widths  = np.zeros(0), width_resampling = 7, ang_smooth_win = 6, length_resampling = 49):
    
    #if np.all(np.isnan(skeleton)):
    #    buff = np.empty((skeleton.shape[0], width_resampling))
    #    buff.fill(np.nan)
    #    return buff
    assert half_width>0 or cnt_widths.size>0
    assert not np.any(np.isnan(skeleton))
    
    if ang_smooth_win%2 == 1:
        ang_smooth_win += 1; 
    
    if skeleton.shape[0] != length_resampling:
        skeleton, _ = curvspace(np.ascontiguousarray(skeleton), length_resampling)
    
    skelX = skeleton[:,0];
    skelY = skeleton[:,1];
    
    assert np.max(skelX) < worm_img.shape[0]
    assert np.max(skelY) < worm_img.shape[1]
    assert np.min(skelY) >= 0
    assert np.min(skelY) >= 0
    
    #calculate smoothed angles
    skel_angles = angleSmoothed(skelX, skelY, ang_smooth_win)
    
    #%get the perpendicular angles to define line scans (orientation doesn't
    #%matter here so subtracting pi/2 should always work)
    perp_angles = skel_angles - np.pi/2;
    
    #%for each skeleton point get the coordinates for two line scans: one in the
    #%positive direction along perpAngles and one in the negative direction (use
    #%two that both start on skeleton so that the intensities are the same in
    #%the line scan)
    
    #resample the points along the worm width
    if half_width <= 0:
        half_width = (np.median(cnt_widths[10:-10])/2.) #add half a pixel to get part of the contour
    r_ind = np.linspace(-half_width, half_width, width_resampling)
    
    #create the grid of points to be interpolated (make use of numpy implicit broadcasting Nx1 + 1xM = NxM)
    grid_x = skelX + r_ind[:, np.newaxis]*np.cos(perp_angles);
    grid_y = skelY + r_ind[:, np.newaxis]*np.sin(perp_angles);
    
    
    f = RectBivariateSpline(np.arange(worm_img.shape[0]), np.arange(worm_img.shape[1]), worm_img)
    return f.ev(grid_y, grid_x) #return interpolated intensity map


def getSkeleton(worm_mask, prev_skeleton = np.zeros(0), resampling_N=50, min_mask_area = 50):
    contour = binaryMask2Contour(worm_mask, min_mask_area=50)
    
    skeleton, cnt_side1, cnt_side2, cnt_widths, ske_len, cnt_side1_len, cnt_side2_len, err_msg = \
    contour2Skeleton(contour, resampling_N)
    
    skeleton, cnt_side1, cnt_side1_len, cnt_side2, cnt_side2_len, cnt_widths = \
    orientWorm(skeleton, prev_skeleton, cnt_side1, cnt_side1_len, cnt_side2, cnt_side2_len, cnt_widths)
    
    return skeleton, ske_len, cnt_side1, cnt_side1_len, cnt_side2, cnt_side2_len, cnt_widths

    #else:
    #    #return all np.nan values, it is easier to work with this in later scripts
    #    buff_nan = np.emtpy((resampling_N,2)).fill(np.nan)
    #    return buff_nan.copy(), np.nan, buff_nan.copy(), np.nan, buff_nan.copy(), np.nan, buff_nan.copy()


if __name__ == '__main__':
    worm_name = 'worm_1717.hdf5' #file where the binary masks are stored
    resampling_N = 50; #number of resampling points of the skeleton
    
    fid = h5py.File(worm_name, 'r');
    data_set = fid['/masks'][:] #ROI with worm binary mask
    worm_CMs = fid['CMs'][:] #center of mass of the ROI
    
    total_frames = data_set.shape[0]
    
    all_skeletons = np.empty((total_frames, resampling_N, 2))
    all_skeletons.fill(np.nan)
    prev_skeleton = np.zeros(0)
    
    tic = time.time()
    
    for frame in range(total_frames):
        print(frame, total_frames)
        worm_mask = data_set[frame,:,:];

        skeleton, ske_len, cnt_side1, cnt_side1_len, cnt_side2, cnt_side2_len, cnt_widths = \
        getSkeleton(worm_mask, prev_skeleton, resampling_N)
        if skeleton.size == 0:
            continue
        prev_skeleton = skeleton
        
        all_skeletons[frame, :, :] = skeleton;
        
        #this function is quite slow due to a 2D interpolation (RectBivariateSpline), 
        #but it might be useful for me in a further analysis of the image textures
        straighten_worm = getStraightenWormInt(worm_mask, skeleton, cnt_widths=cnt_widths, length_resampling=110, width_resampling=13)
        
    print(time.time() - tic)
        
    #%% Plot all skeletons
    #plot every jump frames. otherwise the skeletons overlap too much
    jump = 25 
    
    #add the ROI CMs to show the worm displacements, this value would be offshift by worm_mask.shape/2
    xx = (all_skeletons[:total_frames:jump,:,0] + worm_CMs[:total_frames:jump,0][:, np.newaxis]).T
    yy = (all_skeletons[:total_frames:jump,:,1] + worm_CMs[:total_frames:jump,1][:, np.newaxis]).T
            
    plt.figure()
    plt.plot(xx,yy)
    #%% Plot the results of the last  mask
    plt.figure()
    plt.imshow(worm_mask, cmap= 'gray', interpolation = 'none')
    plt.plot(skeleton[:,0], skeleton[:,1], 'x-g')
    plt.plot(cnt_side1[:,0], cnt_side1[:,1], '.-r')
    plt.plot(cnt_side2[:,0], cnt_side2[:,1], '.-c')
    plt.plot(cnt_side1[0,0], cnt_side1[0,1], 'og')
    plt.plot(cnt_side2[0,0], cnt_side2[0,1], 'og')
    plt.plot(cnt_side1[-1,0], cnt_side1[-1,1], 'sg')
    plt.plot(cnt_side2[-1,0], cnt_side2[-1,1], 'sg')
#%%
    plt.figure()
    plt.imshow(straighten_worm, interpolation = 'none', cmap = 'gray')