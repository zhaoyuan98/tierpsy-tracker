# -*- coding: utf-8 -*-
"""
Created on Mon Feb 22 17:46:36 2016

@author: ajaver
"""
import pandas as pd
import os
import tables
import numpy as np
import matplotlib.pylab as plt
from collections import OrderedDict

import sys
sys.path.append('/Users/ajaver/Documents/GitHub/Multiworm_Tracking')
from MWTracker.helperFunctions.timeCounterStr import timeCounterStr


if __name__ == '__main__':
    #base directory
    #masked_image_file = '/Users/ajaver/Desktop/Videos/Avelino_17112015/MaskedVideos/CSTCTest_Ch5_17112015_205616.hdf5'
    #masked_image_file = '/Users/ajaver/Desktop/Videos/Avelino_17112015/MaskedVideos/CSTCTest_Ch3_17112015_205616.hdf5'
    masked_image_file = '/Users/ajaver/Desktop/Videos/Avelino_17112015/MaskedVideos/CSTCTest_Ch1_18112015_075624.hdf5'
    #masked_image_file = '/Users/ajaver/Desktop/Videos/04-03-11/MaskedVideos/575 JU440 swimming_2011_03_04__13_16_37__8.hdf5'    
    #masked_image_file = '/Users/ajaver/Desktop/Videos/04-03-11/MaskedVideos/575 JU440 on food Rz_2011_03_04__12_55_53__7.hdf5'    
    
    skeletons_file = masked_image_file.replace('MaskedVideos', 'Results1')[:-5] + '_skeletons.hdf5'
    intensities_file = skeletons_file.replace('_skeletons', '_intensities')
    
    min_block_size = 1    
    
    #get the trajectories table
    with pd.HDFStore(skeletons_file, 'r') as fid:
        trajectories_data = fid['/trajectories_data']
        #at this point the int_map_id with the intensity maps indexes must exist in the table
        assert 'int_map_id' in trajectories_data
    
    trajectories_data = trajectories_data[trajectories_data['int_map_id']>0]
    
    grouped_trajectories = trajectories_data.groupby('worm_index_joined')

    tot_worms = len(grouped_trajectories)
    base_name = skeletons_file.rpartition('.')[0].rpartition(os.sep)[-1].rpartition('_')[0]
    progress_timer = timeCounterStr('');
    
    
    valid_data = OrderedDict()
    for index_n, (worm_index, trajectories_worm) in enumerate(grouped_trajectories):
        if index_n % 10 == 0:
            dd = " Correcting Head-Tail using intensity profiles. Worm %i of %i." % (index_n+1, tot_worms)
            dd = base_name + dd + ' Total time:' + progress_timer.getTimeStr()
            print(dd)
        
        
        int_map_id = trajectories_worm['int_map_id'].values
        first_frame = trajectories_worm['frame_number'].min()
        last_frame = trajectories_worm['frame_number'].max()
        
        #only analyze data that contains at least  min_block_size intensity profiles     
        if int_map_id.size < min_block_size:
            continue
        
        #read the worm intensity profiles
        with tables.File(intensities_file, 'r') as fid:
            worm_int_profile = fid.get_node('/straighten_worm_intensity_median')[int_map_id,:]
        
        #%%
        #normalize intensities of each individual profile 
        frame_med_int = np.median(worm_int_profile, axis=1);
        worm_int_profile = worm_int_profile - frame_med_int[:, np.newaxis]
        #worm median intensity
        median_profile = np.median(worm_int_profile, axis=0).astype(np.float)
        
        valid_data[worm_index] = {'median_profile' : median_profile, 
        'int_map_id' : int_map_id, 'frame_med_int' : frame_med_int, 
        'frame_range' : (first_frame,last_frame)}
    
    #%% get valid indexes
    traj_groups = {}
    joined_indexes = {}
    dd = trajectories_data[trajectories_data['worm_label']==1]
    grouped_trajectories_N = dd.groupby('worm_index_N')
    for index_n, (worm_index, trajectories_worm) in enumerate(grouped_trajectories_N):
        joined_indexes[worm_index] = trajectories_worm['worm_index_joined'].unique()
        for wi in joined_indexes[worm_index]:
            traj_groups[wi] = worm_index
#%%
    best_match1 = []
    best_match2 = []
    
    length_resampling = len(median_profile)
    tot_index = len(valid_data)
    
    prob_data = {}    
    
    valid_worm_index = list(valid_data.keys())    
    valid_worm_order = {x:n for n,x in enumerate(valid_worm_index)}
    tot_valid_worms = len(valid_worm_index)
    
    prob_mat = np.full((tot_valid_worms, tot_valid_worms), np.nan)    
    prob_mat2 = np.full((tot_valid_worms, tot_valid_worms), np.nan)    
    
    for worm_index in valid_data:
        
        first_frame = valid_data[worm_index]['frame_range'][0]
        last_frame = valid_data[worm_index]['frame_range'][1]
        
        #filter pausible indexes
        other_worms_ind = valid_worm_index[:]
        other_worms_ind.remove(worm_index)
        
        #trajectories that do not overlap with the current one
        other_worms_ind = [x for x in other_worms_ind 
        if (last_frame < valid_data[x]['frame_range'][0]) or
        (first_frame > valid_data[x]['frame_range'][1])]
      
        #
        other_worm_profile = np.zeros((length_resampling, len(other_worms_ind)))
        for w_ii, w_ind in enumerate(other_worms_ind):
            other_worm_profile[:,w_ii] = valid_data[w_ind]['median_profile']
    
        trajectories_worm = grouped_trajectories.get_group(worm_index)
    
        int_map_id = valid_data[worm_index]['int_map_id']
        frame_med_int = valid_data[worm_index]['frame_med_int']
        median_profile = valid_data[worm_index]['median_profile']
        
        with tables.File(intensities_file, 'r') as fid:
            worm_int_profile = fid.get_node('/straighten_worm_intensity_median')[int_map_id,:]
        
        worm_int_profile -= frame_med_int[:, np.newaxis]
        #%%
        DD = worm_int_profile[:,:,np.newaxis] - other_worm_profile[np.newaxis,:,:]        
        DD = np.mean(np.abs(DD), axis = (0,1))
        
        DD_inv = worm_int_profile[:,:,np.newaxis] - other_worm_profile[np.newaxis,::-1,:]        
        DD_inv = np.mean(np.abs(DD_inv), axis = (0,1))
        
        DD = np.min((DD, DD_inv), axis=0)
        
        wi1 = valid_worm_order[worm_index]
        for ii, x in enumerate(other_worms_ind):
            wi2 = valid_worm_order[x]
            prob_mat[wi1,wi2] = DD[ii]
        
        DD = np.exp(-DD)
        worm_prob = DD/np.sum(DD)#, axis=1)[:,np.newaxis]
        
        #worm_prob = np.sum(worm_prob, axis=0)/worm_prob.shape[0]
        #best_index = np.argmin(DD, axis=1)
        #worm_prob = np.bincount(best_index)/len(best_index)
        
        
        #%%
        
        DD = other_worm_profile - median_profile[:, np.newaxis]
        DD = np.mean(np.abs(DD), axis=0)
        
        DD_inv = other_worm_profile - median_profile[::-1, np.newaxis]
        DD_inv = np.mean(np.abs(DD_inv), axis=0)
        DD = np.min((DD, DD_inv), axis=0)
        
        
        wi1 = valid_worm_order[worm_index]
        for ii, x in enumerate(other_worms_ind):
            wi2 = valid_worm_order[x]
            prob_mat2[wi1,wi2] = DD[ii]
        
        #best_inv = np.argmin((DD, DD_inv), axis=0)
        
        DD = np.exp(-DD)
        worm_prob2 = DD/np.sum(DD)    
        #%%
        if True:
            dd = joined_indexes[traj_groups[worm_index]]
            title_str = '%i: %s' % (worm_index, str(dd))
            plt.figure()
            plt.subplot(1,2,1)
            plt.plot(valid_data[worm_index]['median_profile'], 'k')
            best1 = np.argsort(worm_prob)[:-4:-1]
            for x in best1:
                plt.plot(other_worm_profile[:,x], label=other_worms_ind[x])
            
            plt.legend(loc=4)
            plt.title(title_str)
            
            plt.subplot(1,2,2)
            plt.plot(valid_data[worm_index]['median_profile'], 'k')
            best1 = np.argsort(worm_prob2)[:-4:-1]
            for x in best1:
                plt.plot(other_worm_profile[:,x], label=other_worms_ind[x])
            
            plt.legend(loc=4)
            plt.title(title_str)
        
        
        #%%
        prob_data[worm_index] = {'other_worms_ind':other_worms_ind, 
        'worm_prob':worm_prob, 'worm_prob2':worm_prob2}    
        
        if len(worm_prob) == 0:
            continue
        ii = np.argmax(worm_prob)        
        best_match1.append((worm_index, other_worms_ind[ii], worm_prob[ii]))

        ii = np.argmax(worm_prob2)                
        best_match2.append((worm_index, other_worms_ind[ii], worm_prob2[ii]))
        #%%
    
    #%%
    good = ~np.isnan(prob_mat)
    DD = np.exp(-prob_mat[good])
    prob_mat[good] = DD/np.sum(DD)
    
    good = ~np.isnan(prob_mat2)
    DD = np.exp(-prob_mat2[good])
    prob_mat2[good] = DD/np.sum(DD)
    
    plt.figure()
    plt.plot(np.sort(prob_mat[~np.isnan(prob_mat)]), '.')
    plt.plot(np.sort(prob_mat2[~np.isnan(prob_mat2)]), '.')
    #%%
    worm_index = 3
    prob_data[worm_index]
    worm_prob2 = prob_data[worm_index]['worm_prob2']
    other_worms_ind = prob_data[worm_index]['other_worms_ind']
#%%
from sklearn.cluster import k_means
    
tot_prof = len(valid_data)

median_profiles = np.zeros((2*tot_prof, length_resampling))
for ii, worm_index in enumerate(valid_data.keys()):
    median_profiles[2*ii, :] = valid_data[worm_index]['median_profile']
    median_profiles[2*ii+1, :] = valid_data[worm_index]['median_profile'][::-1] #consider the case that there are wrong head tail assigments
    
#%%

centroid, label, inertia = k_means(median_profiles, 16)
plt.figure()
for ii in range(16):
    plt.plot(centroid[ii])
    
    