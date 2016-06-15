# -*- coding: utf-8 -*-
"""
Created on Tue Jun  9 15:12:48 2015

@author: ajaver
"""

import os
import sys
import tables
import fnmatch

from MWTracker.helperFunctions.timeCounterStr import timeCounterStr
from MWTracker.compressVideos.getAdditionalData import getAdditionalFiles
from MWTracker.compressVideos.extractMetaData import correctTimestamp
from MWTracker.compressVideos.compressVideo import selectVideoReader


def exploreDirs(root_dir, pattern_include = '*', pattern_exclude = ''):
	root_dir = os.path.abspath(root_dir)
	assert os.path.exists(root_dir)
	
	#if there is only a string (only one pattern) let's make it a list to be able to reuse the code
	if not isinstance(pattern_include, (list, tuple)): pattern_include = [pattern_include]
	if not isinstance(pattern_exclude, (list, tuple)): pattern_exclude = [pattern_exclude]

	valid_files = []
	for dpath, dnames, fnames in os.walk(root_dir):
		for fname in fnames:
			good_patterns = any(fnmatch.fnmatch(fname, dd) for dd in pattern_include)
			bad_patterns = any(fnmatch.fnmatch(fname, dd) for dd in pattern_exclude)
			if good_patterns and not bad_patterns:
				fullfilename = os.path.abspath(os.path.join(dpath, fname))
				assert os.path.exists(fullfilename)
				valid_files.append(fullfilename)
	
	return valid_files


def isBadVideo(video_file, is_single_worm):
	try:
		vid, im_width, im_height, reader_type = selectVideoReader(video_file)
		vid.release() # i have problems with corrupt videos that can create infinite loops...
		if is_single_worm: 
			#check for the additional files in the case of single worm
			try:
			#this function will throw and error if the .info.xml or .log.csv are not found
				info_file, stage_file = getAdditionalFiles(video_file)
			except (IOError, FileNotFoundError):
				return True
	except OSError:
		#corrupt file, cannot read the size
		return True
	return False


def isBadMask(masked_image_file):
	#test if the file finished correctly
	try:
		with tables.File(masked_image_file, 'r') as mask_fid:
			mask_node = mask_fid.get_node('/mask')
			if ('has_finished' in mask_node._v_attrs) and (mask_node._v_attrs['has_finished'] < 1): 
				raise ValueError
			if mask_node.shape[0] == 0:
				raise ValueError
	except (tables.exceptions.HDF5ExtError, tables.exceptions.NoSuchNodeError, ValueError, IOError):
		return True
	#no problems with the file
	return False


def getDstDir(source_dir, source_root_dir, dst_root_dir):
	'''
	Generate the destination dir path keeping the same structure as the source directory
	'''

	subdir_path = source_dir.replace(source_root_dir, '')
	
	#consider the case the subdirectory is only a directory separation character
	if subdir_path and subdir_path[0] == os.sep: 
		subdir_path = subdir_path[1:] if len(subdir_path) >1 else ''
	dst_dir = os.path.join(dst_root_dir, subdir_path)

	return dst_dir

class checkVideoFiles:
	def __init__(self, video_dir_root, mask_dir_root, \
		tmp_dir_root = '', is_copy_video=False, \
		is_single_worm = False, json_file = '', \
		no_skel_filter = False, use_manual_join = False,\
		script_abs_path = './compressSingleLocal.py'):
		
		#checkings before accepting the data
		video_dir_root = os.path.abspath(video_dir_root)
		assert os.path.exists(video_dir_root)
		
		mask_dir_root = os.path.abspath(mask_dir_root)
		if not os.path.exists(mask_dir_root):
			os.makedirs(mask_dir_root)
		
		assert os.path.exists(script_abs_path)

		if json_file: 
			json_file = os.path.abspath(json_file)
			assert os.path.exists(json_file)
		
		if tmp_dir_root: 
			tmp_dir_root = os.path.abspath(tmp_dir_root)
			if not os.path.exists(tmp_dir_root):
				os.makedirs(tmp_dir_root)
		
		self.video_dir_root = video_dir_root
		self.json_file = json_file
		self.script_abs_path = script_abs_path
		self.is_single_worm = is_single_worm
		self.is_copy_video = is_copy_video
		self.no_skel_filter = no_skel_filter
		self.use_manual_join = use_manual_join
		
		#Let's look look for a MaskedVideos subdirectory, otherwise we add it at the end of the root dir
		self.mask_dir_root = self.checkMaskPrefix(mask_dir_root)
		#If tmp_dir_root is empty let's use the mask_dir_root as our source
		self.tmp_dir_root = self.checkMaskPrefix(tmp_dir_root) if tmp_dir_root else self.mask_dir_root

		self.filtered_files_fields = ('SOURCE_GOOD', 'SOURCE_BAD', 'FINISHED_GOOD', 'FINISHED_BAD')
		self.filtered_files = {key : [] for key in self.filtered_files_fields}
		
	def checkIndFile(self, video_file):
		
		video_dir, video_file_name = os.path.split(video_file)
		mask_dir = getDstDir(video_dir, self.video_dir_root, self.mask_dir_root)
		masked_image_file = self.getMaskName(video_file, mask_dir)
		
		if os.path.exists(masked_image_file):
			if not isBadMask(masked_image_file):
				return 'FINISHED_GOOD' , (video_file, masked_image_file)
			else:
				return 'FINISHED_BAD', (video_file, masked_image_file)
				
		
		else:
			if isBadVideo(video_file, self.is_single_worm):
				return 'SOURCE_BAD', video_file
			else:
				return 'SOURCE_GOOD', video_file


	def filterFiles(self, valid_files):
		#intialize filtered files lists
		self.filtered_files = {key : [] for key in self.filtered_files_fields}
		
		progress_timer = timeCounterStr('');
		for ii, video_file in enumerate(valid_files):
			label, proccesed_file = self.checkIndFile(video_file)
			assert label in self.filtered_files_fields

			self.filtered_files[label].append(proccesed_file)

			if (ii % 10) == 0:
				print('Checking file %i of %i. Total time: %s' % (ii+1, len(valid_files), progress_timer.getTimeStr()))
		
		print('Finished to check files. Total time elapsed %s' % progress_timer.getTimeStr())


	@staticmethod
	def checkMaskPrefix(fdir):
		#check if the root dir has a subfolder MaskedVideos otherwise add it to the end
		N = sum('MaskedVideos' == part for part in fdir.split(os.sep))

		if N > 1: 
			raise ValueError('Only one subdirectory is allowed to be named "MaskedVideos"')
			
		if N == 0:
			fdir =  os.path.join(fdir, 'MaskedVideos')
		return os.path.abspath(fdir)

	def getCMDlist(self):
		good_video_files = self.filtered_files['SOURCE_GOOD']
		
		cmd_list = []
		for video_file in good_video_files:
			cmd_list.append(self.generateIndCMD(video_file))
		return cmd_list

	def generateIndCMD(self, video_file):
		video_dir, video_file_name = os.path.split(video_file)
		
		mask_dir = getDstDir(video_dir, self.video_dir_root, self.mask_dir_root)
		tmp_mask_dir = getDstDir(video_dir, self.video_dir_root, self.tmp_dir_root)

		if not os.path.exists(mask_dir): os.makedirs(mask_dir)
		if not os.path.exists(tmp_mask_dir): os.makedirs(tmp_mask_dir)
					
		#create a command line with the required arguments
		cmd = [sys.executable, self.script_abs_path, video_file, mask_dir]
		
		json_file = self.json_file
		#add the optional arguments if they are present
		for arg in ['tmp_mask_dir', 'json_file']:
			tmp_val = eval(arg)
			if tmp_val: cmd += ['--' + arg, tmp_val]
		
		if self.is_single_worm: cmd.append('--is_single_worm')
		if self.is_copy_video: cmd.append('--is_copy_video')

		return cmd

	def cleanPrevious(self):
		''' Delete any bad finished files.'''
		for video_file, masked_image_file in self.filtered_files['FINISHED_BAD']:
			assert masked_image_file[-5:] == '.hdf5'
			
			#delete wrong file from previous analysis
			if os.name != 'nt':	
				os.chflags(masked_image_file, not stat.UF_IMMUTABLE)
			os.remove(masked_image_file)

			#add the video to files to be processed
			label, proccesed_file = self.checkIndFile(video_file)
			assert label in self.filtered_files_fields
			self.filtered_files[label].append(proccesed_file)
			

		self.filtered_files['FINISHED_BAD'] = []

	@staticmethod
	def getMaskName(video_file, mask_dir):
		base_name = video_file.rpartition('.')[0].rpartition(os.sep)[-1]
		masked_image_file = os.path.join(mask_dir, base_name + '.hdf5')
		return masked_image_file


	
	

	
	
    