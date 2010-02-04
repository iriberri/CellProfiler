'''<b>Load Images</b> allows you to specify which images or movies are to be loaded and in
which order
<hr>
Tells CellProfiler where to retrieve images and gives each image a
meaningful name for the other modules to access. The relationships between images and metadata describing each image can also be extracted or defined in this module. For example, a group of images (such as three channels that represent the same field of view) can be loaded together to be processed in a single cycle of CellProfiler processing.

When used in combination
with a <b>SaveImages</b> module, you can load images in one file format and
save in another file format, making CellProfiler work as a file format
converter.

See also <b>LoadSingleImage</b>,<b>SaveImages</b>
'''
# CellProfiler is distributed under the GNU General Public License.
# See the accompanying file LICENSE for details.
# 
# Developed by the Broad Institute
# Copyright 2003-2010
# 
# Please see the AUTHORS file for credits.
# 
# Website: http://www.cellprofiler.org

__version__="$Revision$"

import numpy as np
import cgi
import hashlib
import httplib
import os
import re
import sys
import stat
import tempfile
import traceback
import urllib
import wx
import wx.html

try:
    import bioformats.formatreader as formatreader
    formatreader.jutil.attach()
    try:
        FormatTools = formatreader.make_format_tools_class()
        ImageReader = formatreader.make_image_reader_class()
        ChannelSeparator = formatreader.make_reader_wrapper_class(
            "loci/formats/ChannelSeparator")
        has_bioformats = True
    finally:
        formatreader.jutil.detach()
except:
    has_bioformats = False
import Image as PILImage
#
# Load all the PIL image plugins to initialize PIL in the
# compiled version of CP
#
import BmpImagePlugin
import DcxImagePlugin
import EpsImagePlugin
import GifImagePlugin
import JpegImagePlugin
import PngImagePlugin
import TiffImagePlugin as TIFF
import cellprofiler.dib
import matplotlib.image
import scipy.io.matlab.mio
import uuid

import cellprofiler.cpmodule as cpmodule
import cellprofiler.cpimage as cpimage
import cellprofiler.measurements as cpm
import cellprofiler.preferences as preferences
import cellprofiler.settings as cps

PILImage.init()

'''STK TIFF Tag UIC1 - for MetaMorph internal use'''
UIC1_TAG = 33628
'''STK TIFF Tag UIC2 - stack z distance, creation time...'''
UIC2_TAG = 33629
'''STK TIFF TAG UIC3 - wavelength'''
UIC3_TAG = 33630
'''STK TIFF TAG UIC4 - internal'''
UIC4_TAG = 33631

# strings for choice variables
MS_EXACT_MATCH = 'Text-Exact match'
MS_REGEXP = 'Text-Regular expressions'
MS_ORDER = 'Order'

FF_INDIVIDUAL_IMAGES = 'individual images'
FF_STK_MOVIES = 'stk movies'
FF_AVI_MOVIES = 'avi movies'
FF_OTHER_MOVIES = 'tif,tiff,flex movies'
if has_bioformats:
    FF = [FF_INDIVIDUAL_IMAGES, FF_STK_MOVIES, FF_AVI_MOVIES, FF_OTHER_MOVIES]
else:
    FF = [FF_INDIVIDUAL_IMAGES, FF_STK_MOVIES]

USE_BIOFORMATS_FIRST = [".tiff", ".tif", ".flex",".stk"]
DIR_DEFAULT_IMAGE = 'Default Image Folder'
DIR_DEFAULT_OUTPUT = 'Default Output Folder'
DIR_OTHER = 'Elsewhere...'

SB_GRAYSCALE = 'grayscale'
SB_BINARY = 'binary'

FD_KEY = "Key"
FD_COMMON_TEXT = "CommonText"
FD_ORDER_POSITION = "OrderPosition"
FD_IMAGE_NAME = "ImageName"
FD_REMOVE_IMAGE = "RemoveImage"
FD_METADATA_CHOICE = "MetadataChoice"
FD_FILE_METADATA = "FileMetadata"
FD_PATH_METADATA = "PathMetadata"

# The metadata choices:
# M_NONE - don't extract metadata
# M_FILE_NAME - extract metadata from the file name
# M_PATH_NAME - extract metadata from the subdirectory path
# M_BOTH      - extract metadata from both the file name and path
M_NONE      = "None"
M_FILE_NAME = "File name"
M_PATH      = "Path"
M_BOTH      = "Both"

#
# FLEX metadata
#
M_Z = "Z"
M_T = "T"
M_SERIES = "Series"

'''The provider name for the image file image provider'''
P_IMAGES = "LoadImagesImageProvider"
'''The version number for the __init__ method of the image file image provider'''
V_IMAGES = 1

'''The provider name for the movie file image provider'''
P_MOVIES = "LoadImagesMovieProvider"
'''The version number for the __init__ method of the movie file image provider'''
V_MOVIES = 1

'''The provider name for the flex file image provider'''
P_FLEX = 'LoadImagesFlexFrameProvider'
'''The version number for the __init__ method of the flex file image provider'''
V_FLEX = 1

def default_cpimage_name(index):
    # the usual suspects
    names = ['DNA', 'Actin', 'Protein']
    if index < len(names):
        return names[index]
    return 'Channel%d'%(index+1)

class LoadImages(cpmodule.CPModule):

    module_name = "LoadImages"
    variable_revision_number = 4
    category = "File Processing"

    def create_settings(self):
        # Settings
        self.file_types = cps.Choice('What type of files are you loading?', FF, doc="""
                The following image file types are permissible for input into CellProfiler:
                <ul>
                <li><i>Individual images:</i>Each file represents a single image. 
                Some methods of file compression sacrifice image quality ("lossy") and should be avoided for automated image analysis 
                if at all possible (e.g., .jpg). Other file compression formats retain exactly the original image information but in 
                a smaller file ("lossless") so they are perfectly acceptable for image analysis (e.g., .png, .tif, .gif). 
                Uncompressed file formats are also fine for image analysis (e.g., .bmp)</li>
                <li><i>AVI movies:</i>An AVI (Audio Video Interleave) file is a type of movie file. Only uncompressed AVIs are supported.
                Files are opened as a stack of images.</li>
                <li><i>TIF,TIFF,FLEX movies:</i>A TIF/TIFF movie is a file in which a series of images are contained as individual frames. 
                The same is true for the FLEX file format (used by Evotec Opera automated microscopes). Files are opened as a stack of images.</li>
                <li><i>STK movies:</i> STKs are a proprietary image format used by MetaMorph (Molecular Devices). It is typically
                used to encode 3D image data, e.g. from confocal microscopy, and is a special version of the TIF format. </li>
                </ul>
                For the movie formats, the files are opened as a stack of images and each image is processed individually.""")
        
        self.match_method = cps.Choice('How do you want to load these files?', [MS_EXACT_MATCH, MS_REGEXP, MS_ORDER],doc="""
                Three options are available:
                <ul>
                <li><i>Order:</i> Used when images (or movies) are present in a repeating order,
                like <i>DAPI, FITC, Red, DAPI, FITC, Red</i>, and so on, where images are
                selected based on how many images are in each group and what position
                within each group a particular color is located (e.g. three images per
                group, DAPI is always first).
                <li><i>Text - Exact match:</i> Used to load images (or movies) that have a particular piece of
                text in the name. The specific text that is entered will be searched for in the filenames and
                the images that contain that text exactly will be loaded. The search for the text is case-sensitive so
                keep that in mind.
                <li><i>Text - Regular expressions:</i> When regular expressions is selected, patterns are specified using
                combinations of metacharacters and literal characters. There are a few
                classes of metacharacters, partially listed below. A more extensive
                explanation can be found <a href="http://www.python.org/doc/2.3/lib/re-syntax.html">here</a>
                and a helpful quick reference can be found <a href="http://www.addedbytes.com/cheat-sheets/regular-expressions-cheat-sheet/">here</a>.
                <p>The following metacharacters match exactly one character from its respective set of characters:
                <table border="1">
                <tr><th>Metacharacter</th><th>Meaning</th></tr>
                <tr><td>.</td><td>Any character</td></tr>
                <tr><td>[]</td><td>Any character contained within the brackets</td></tr>
                <tr><td>[^]</td><td>Any character not contained within the brackets</td></tr>
                <tr><td>\w</td><td>A word character [a-z_A-Z0-9]</td></tr>
                <tr><td>\W</td><td>Not a word character [^a-z_A-Z0-9]</td></tr>
                <tr><td>\d</td><td>A digit [0-9]</td></tr>
                <tr><td>\D</td><td>Not a digit [^0-9]</td></tr>
                <tr><td>\s</td><td>Whitespace [ \\t\\r\\n\\f\\v]</td></tr>
                <tr><td>\S</td><td>Not whitespace [^ \\t\\r\\n\\f\\v]</td></tr>
                </table>
        
                <p>The following metacharacters are used to logically group subexpressions
                or to specify context for a position in the match. These metacharacters
                do not match any characters in the string:
                <table border="1">
                <tr><th>Metacharacter</th><th>Meaning</th></tr>
                <tr><td>( )</td><td>Group subexpression</td></tr>
                <tr><td>|</td><td>Match subexpression before or after the |</td></tr>
                <tr><td>^</td><td>Match expression at the start of string</td></tr>
                <tr><td>$</td><td>Match expression at the end of string</td></tr>
                <tr><td>\\< </td><td>Match expression at the start of a word</td></tr>
                <tr><td>\> </td><td>Match expression at the end of a word</td></tr>
                </table>
                
                <p>The following metacharacters specify the number of times the previous
                metacharacter or grouped subexpression may be matched:
                <table border="1">
                <tr><th>Metacharacter</th><th>Meaning</th></tr>
                <tr><td>*</td><td>Match zero or more occurrences</td></tr>
                <tr><td>+</td><td>Match one or more occurrences</td></tr>
                <tr><td>?</td><td>Match zero or one occurrence</td></tr>
                <tr><td>{n,m}</td><td>Match between n and m occurrences</td></tr>
                </table>
                
                <p>Characters that are not special metacharacters are all treated literally
                in a match. To match a character that is a special metacharacter, escape
                that character with a '\\'. For example '.' matches any character, so to
                match a '.' specifically, use '\.' in your pattern.
                
                Examples:
                <ul>
                <li>[trm]ail matches 'tail' or 'rail' or 'mail'</li>
                <li>[0-9] matches any digit between 0 to 9</li>
                <li>[^Q-S] matches any character other than 'Q' or 'R' or 'S'</li>
                <li>[[]A-Z] matches any upper case alphabet along with square brackets</li>
                <li>[ag-i-9] matches characters 'a' or 'g' or 'h' or 'i' or '-' or '9'</li>
                <li>[a-p]* matches '' or 'a' or 'aab' or 'p' etc.</li>
                <li>[a-p]+ matches  'a' or 'abc' or 'p' etc.</li>
                <li>[^0-9] matches any string that is not a number</li>
                <li>^[0-9]*$ matches any string that is a natural number or ''</li>
                <li>^-[0-9]+$|^\+?[0-9]+$ matches any integer</li>
                </ul>
                </ul>""")
        
        self.exclude = cps.Binary('Do you want to exclude certain files?', False,doc="""
                <i>(Only used if loading files using Text-Exact match is selected)</i> 
                <p>The image/movie files specified with the <i>Text</i> options may also include
                files that you want to exclude from analysis (such as thumbnails created 
                by an imaging system).""")
        
        self.match_exclude = cps.Text('Type the text that the excluded images have in common', cps.DO_NOT_USE,doc="""
                <i>(Only used if file exclusion is selected)</i> 
                <p>Here you can specify text that mark files for exclusion. This text is treated as a 
                exact match within the filename and not as a regular expression. """)
        
        self.order_group_size = cps.Integer('How many images are there in each group?', 3,doc="""
                <i>(Only used when Order is used for file loading)</i>
                <p>Enter the number of images that comprise a group. For example, for images given in the order:
                <i>DAPI, FITC, Red, DAPI, FITC, Red</i>, and so on, the number would be 3.""")
        
        self.descend_subdirectories = cps.Binary('Analyze all subfolders within the selected folder?', False, doc="""
                If this box is checked, all the subfolders under the image folder location that you specify will be
                searched for images matching the criteria above.""")
        
        self.check_images = cps.Binary('Do you want to check image sets for missing or duplicate files?',True,doc="""
                Selecting this option will examine the filenames for 
                unmatched or duplicate files based on the filename prefix (such as those 
                generated by HCS systems).""")
        
        self.group_by_metadata = cps.Binary('Do you want to group image sets by metadata?',False,doc="""
                In some instances, you may want to process as a group those images that share a particular
                metadata tag. For example, if performing per-plate illumination correction, and the
                plate metadata is part of the image filename, using image grouping will you to
                process those images that have the same plate field together (the alternative would be
                to place the images from each plate in a separate folder). The next setting allows you
                to select the metadata tags by which to group.""")
        
        self.metadata_fields = cps.MultiChoice('What metadata fields do you want to group by?',[],doc="""
                <i>(Only used if grouping image sets by metadata)</i> 
                <p>Select the fields that you want group the image files by here. Multiple tags may be selected. For
                example, if a set of images had metadata for <i>Run</i>,<i>Plate</i>,<i>Well</i> and
                <i>Site</i>, selecting <i>Run</i> and <i>Plate</i> will create groups containing 
                images that share the same [<i>Run</i>,<i>Plate</i>] pair of fields.""")
        
        # Add the first image to the images list
        self.images = []
        self.add_imagecb()
        # Add another image
        self.add_image = cps.DoSomething("", "Add another image", self.add_imagecb)
        
        # Location settings
        self.location = cps.Choice('Image location',
                                        [DIR_DEFAULT_IMAGE, DIR_DEFAULT_OUTPUT, DIR_OTHER],doc="""
                You have the choice of loading the image files from the Default Input folder, the Default Output
                folder or another location entirely.""")
        self.location_other = cps.DirectoryPath("Enter the full path to the images", '',doc="""
                <i>(Only used if your images are located Elsewhere)</i> 
                <p>Type the full path to where the images are located. Note that this
                path is fixed with respect to your local machine, which means that transfering
                your pipeline to another machine may cause it to fail if it does not share the
                same mapping to the same location. We recommend using Default Input/Output
                folders since these locations are set relative to the local machine.""")

    def add_imagecb(self):
        'Adds another image to the settings'
        img_index = len(self.images)
        new_uuid = uuid.uuid1()
        def example_file_fn(path=None):
            '''Get an example file for use in the file metadata regexp editor'''
            if path == None:
                path = self.image_directory()
                default = "plateA-2008-08-06_A12_s1_w1_[89A882DE-E675-4C12-9F8E-46C9976C4ABE].tif"
            else:
                default = None
            #
            # Find out the index we expect from filter_filename
            #
            for i, group in enumerate(self.images):
                if group[FD_KEY] == new_uuid:
                    break
                
            filenames = [x for x in os.listdir(path)
                         if x.find('.') != -1 and
                         os.path.splitext(x)[1].upper() in
                         ('.TIF','.JPG','.PNG','.BMP')]
            filtered_filenames = [x for x in filenames
                                  if self.filter_filename(x) == i]
            if len(filtered_filenames) > 0:
                return filtered_filenames[0]
            if len(filenames) > 0:
                return filenames[0]
            if self.analyze_sub_dirs():
                d = [x for x in [os.path.abspath(os.path.join(path, x))
                                 for x in os.listdir(path)
                                 if not x.startswith('.')]
                     if os.path.isdir(x)]
                for subdir in d:
                    result = example_file_fn(subdir)
                    if result is not None:
                        return result
            return default
        
        def example_path_fn():
            '''Get an example path for use in the path metadata regexp editor'''
            root = self.image_directory()
            d = [x for x in [os.path.abspath(os.path.join(root, x))
                             for x in os.listdir(root)
                             if not x.startswith('.')]
                 if os.path.isdir(x)]
            if len(d) > 0:
                return d[0]
            return root
        
        fd = { FD_KEY:new_uuid,
               FD_COMMON_TEXT:cps.Text('Type the text that these images have in common (case-sensitive)', '',doc="""
                        <i>(Only used for the Text options for image loading)</i>
                        <p>For <i>Text-Exact match</i>, type the text string that all the images have in common. For example,
                        if all the images for the given channel end with the text <i>D.TIF</i>, type <i>D.TIF</i> here.
                        <p>For <i>Text-Regular expression</i>, type the regular expression that would capture all
                        the images for this channel."""),
               FD_ORDER_POSITION:cps.Integer('What is the position of this image in each group?', img_index+1,doc="""
                        <i>(Only used for the Order option for image loading)</i>
                        <p>Enter the number in the image order that this image channel occupies. For example, if 
                        the order is <i>DAPI, FITC, Red, DAPI, FITC, Red</i>, and so on, the <i>DAPI</i> channel
                        would occupy position 1."""),
               FD_IMAGE_NAME:cps.FileImageNameProvider('What do you want to call this image in CellProfiler?', 
                                                       default_cpimage_name(img_index),doc="""
                        Give your images a meaningful name that you will use when referring to
                        these images in later modules.  Keep the following points in mind when deciding 
                        on an image name:
                        <ul>
                        <li>Image names must begin with a letter, which may be followed by any 
                        combination of letters, digits, and underscores. The following names are all invalid:
                        <ul>
                        <li>My.Cells</li>
                        <li>1stCells</li>
                        <li>1+1=3</li>
                        <li>@MyCell</li>
                        </ul>
                        </li>
                        <li>Names are not case senstive. Therefore, <i>OrigBlue</i>, <i>origblue</i>, and <i>ORIGBLUE</i>
                        will correspond to the same name, and unexpected results may ensue.</li>
                        <li>Although the names can be of any length in CellProfiler, you may want to avoid 
                        making the name too long especially if you are uploading to a database. The name is used
                        to generate the column header for a given measurement, and in MySQL, the total bytes used
                        for the column headers cannot exceed 64K. A warning will be generated later if this limit
                        has been exceeded.</li>
                        </ul>"""),
               FD_METADATA_CHOICE:cps.Choice('Do you want to extract metadata from the file name, the subfolder path or both?',
                                             [M_NONE, M_FILE_NAME, 
                                              M_PATH, M_BOTH],doc="""
                        Metadata fields can be specified from the image filename, the image path, or both. 
                        The metadata entered here can be used for image grouping (see the  
                        <i>Do you want to group image sets by metadata?</i> setting) or simply used as 
                        additional columns in the exported measurements (see the <b>ExportToExcel</b> module)"""),
               FD_FILE_METADATA: cps.RegexpText('Type the regular expression that finds metadata in the file name:',
                                                '^(?P<Plate>.*)_(?P<Well>[A-P][0-9]{2})_s(?P<Site>[0-9])',
                                                get_example_fn = example_file_fn,
                        doc="""
                        <i>(Only used if you want to extract metadata from the file name)</i>
                        <p>The regular expression to extract the metadata from the file name is entered here. Note that
                        this field is available whether you have selected <i>Text-Regular expressions</i> to load
                        the files or not. Please see the module help for more information on construction of
                        a regular expression.
                        <p>Clicking the magnifying glass icon to the right will bring up a tool that will allow you to
                        check the accuracy of your regular expression. The regular expression syntax can be used to 
                        name different parts of your expression. The syntax for this is <i>(?&lt;fieldname&gt;expr)</i> to
                        extract whatever matches <i>expr</i> and assign it to the measurement,<i>fieldname</i> for the image.
                        <p>For instance, a researcher uses plate names composed of a string of letters and numbers,
                        followed by an underbar, then the well, followed by another underbar, followed by an "s" and a digit
                        representing the site taken within the well (e.g.,<i>TE12345_A05_s1.tif</i>).
                        The following regular expression will capture the plate, well and site in the fields, <i>Plate</i>, 
                        <i>Well</i> and <i>Site</i>:<br>
                        <table border = "1">
                        <tr><td colspan = "2">^(?P&lt;Plate&gt;.*)_(?P&lt;Well&gt;[A-P][0-9]{1,2})_s(?P&lt;Site&gt;[0-9])</td></tr>
                        <tr><td>^</td><td>Only start at beginning of the file name</td></tr>
                        <tr><td>(?P&lt;Plate&gt;</td><td>Name the captured field, <i>Plate</i></td></tr>
                        <tr><td>.*</td><td>Capture as many characters that follow</td></tr>
                        <tr><td>_</td><td>Discard the underbar separating plate from well</td></tr>
                        <tr><td>(?P&lt;Well&gt;</td><td>Name the captured field, <i>Well</i></td></tr>
                        <tr><td>[A-P]</td><td>Capture exactly one letter between A and P</td></tr>
                        <tr><td>[0-9]{2}</td><td>Capture exactly two digits that follow</td></tr>
                        <tr><td>_s</td><td>Discard the underbar followed by <i>s</s> separating well from site</td></tr>
                        <tr><td>(?P&lt;Site&gt;</td><td>Name the captured field, <i>Site</i></td></tr>
                        <tr><td>[0-9]</td><td>Capture one digit following</td></tr>
                        </table>
                        <p>The regular expression can be typed in the upper text box, with a sample file name given in the lower
                        text box. Provided the syntax is correct, the corresponding fields will be highlighted in the same
                        color in the two boxes. Press <i>Submit</i> to accept the typed regular expression."""),
               FD_PATH_METADATA: cps.RegexpText(
                        'Type the regular expression that finds metadata in the subfolder path:',
                        '.*[\\\\/](?P<Date>.*)[\\\\/](?P<Run>.*)$',
                        get_example_fn = example_path_fn,
                        doc="""
                        <i>(Only used if you want to extract metadata from the path)</i>
                        <p>The regular expression to extract the metadata from the path is entered here. Note that
                        this field is available whether you have selected <i>Text-Regular expressions</i> to load
                        the files or not. Please see the module help for more information on construction of
                        a regular expression.
                        <p>Clicking the magnifying glass icon to the right will bring up a tool that will allow you to
                        check the accuracy of your regular expression. The regular expression syntax can be used to 
                        name different parts of your expression. The syntax for this is <i>(?&lt;fieldname&gt;expr)</i> to
                        extract whatever matches <i>expr</i> and assign it to the measurement, <i>fieldname</i> for the image.
                        <p>For instance, a researcher uses folder names with the date and subfolders containing the
                        images with the run ID (e.g., <i>./2009_10_02/1234/</i>)
                        The following regular expression will capture the plate, well and site in the fields 
                        <i>Date</i> and <i>Run</i>:<br>
                        <table border = "1">
                        <tr><td colspan = "2">.*[\\\/](?P&lt;Date&gt;.*)[\\\\/](?P&lt;Run&gt;.*)$</td></tr>
                        <tr><td>.*[\\\\/]</td><td>Skip characters at the beginning of the pathname until either a slash (/) or
                        backslash (\\) is encountered (depending on the OS)</td></tr>
                        <tr><td>(?P&lt;Date&gt;</td><td>Name the captured field, <i>Date</i></td></tr>
                        <tr><td>.*</td><td>Capture as many characters that follow</td></tr>
                        <tr><td>[\\\\/]</td><td>Discard the slash/backslash character</td></tr>
                        <tr><td>(?P&lt;Run&gt;</td><td>Name the captured field, <i>Run</i></td></tr>
                        <tr><td>.*</td><td>Capture as many characters that follow</td></tr>
                        <tr><td>$</td><td>The <i>Run</i> field must be at the end of the path string, i.e. the
                        last folder on the path. This also means that the <i>Date</i> field contains the parent
                        folder of the <i>Date</i> folder.</td></tr>
                        </table>"""),
               FD_REMOVE_IMAGE:cps.DoSomething('', 'Remove this image',self.remove_imagecb, new_uuid)
               }
        self.images.append(fd)

    def remove_imagecb(self, id):
        'Remove an image from the settings'
        index = [fd[FD_KEY] for fd in self.images].index(id)
        del self.images[index]

    def visible_settings(self):
        varlist = [self.file_types, self.match_method]
        
        if self.match_method == MS_EXACT_MATCH:
            varlist += [self.exclude]
            if self.exclude.value:
                varlist += [self.match_exclude]
        elif self.match_method == MS_ORDER:
            varlist += [self.order_group_size]
        varlist += [self.descend_subdirectories]
        do_flex = self.file_types == FF_OTHER_MOVIES
        if not do_flex:
            if len(self.images) > 1:
                varlist += [self.check_images]
        varlist += [self.group_by_metadata]
        if self.group_by_metadata.value:
            varlist += [self.metadata_fields]
            choices = set()
            for fd in self.images:
                for setting, tag in ((fd[FD_FILE_METADATA], M_FILE_NAME),
                                     (fd[FD_PATH_METADATA], M_PATH)):
                    if fd[FD_METADATA_CHOICE].value in (tag, M_BOTH):
                        choices.update(
                            cpm.find_metadata_tokens(setting.value))
            if self.file_types == FF_OTHER_MOVIES:
                choices.update([M_Z,M_T,M_SERIES])
            choices = list(choices)
            choices.sort()
            self.metadata_fields.choices = choices
        
        # per image settings
        if self.match_method != MS_ORDER:
            file_kwd = FD_COMMON_TEXT
        else:
            file_kwd = FD_ORDER_POSITION
        
        for i,fd in enumerate(self.images):
            if do_flex:
                varlist += [fd[FD_IMAGE_NAME]]
                if i == 0:
                    varlist += [fd[file_kwd]]
            else:
                varlist += [fd[file_kwd], 
                            fd[FD_IMAGE_NAME]]
            if i == 0 or not do_flex:
                varlist += [fd[FD_METADATA_CHOICE]]
                if fd[FD_METADATA_CHOICE].value in (M_FILE_NAME, M_BOTH):
                    varlist.append(fd[FD_FILE_METADATA])
                if fd[FD_METADATA_CHOICE].value in (M_PATH, M_BOTH):
                    varlist.append(fd[FD_PATH_METADATA])
            varlist.append(fd[FD_REMOVE_IMAGE])
        varlist += [self.add_image]
        varlist += [self.location]
        if self.location == DIR_OTHER:
            varlist += [self.location_other]
        return varlist
    
    #
    # Slots for storing settings in the array
    #
    SLOT_FILE_TYPE = 0
    SLOT_MATCH_METHOD = 1
    SLOT_ORDER_GROUP_SIZE = 2
    SLOT_MATCH_EXCLUDE = 3
    SLOT_DESCEND_SUBDIRECTORIES = 4
    SLOT_LOCATION = 5
    SLOT_LOCATION_OTHER = 6
    SLOT_CHECK_IMAGES = 7
    SLOT_FIRST_IMAGE_V1 = 8
    SLOT_GROUP_BY_METADATA = 8
    SLOT_EXCLUDE = 9
    SLOT_GROUP_FIELDS = 10
    SLOT_FIRST_IMAGE_V2 = 9
    SLOT_FIRST_IMAGE_V3 = 10
    SLOT_FIRST_IMAGE = 11
    
    SLOT_OFFSET_COMMON_TEXT = 0
    SLOT_OFFSET_IMAGE_NAME = 1
    SLOT_OFFSET_ORDER_POSITION = 2
    SLOT_OFFSET_METADATA_CHOICE = 3
    SLOT_OFFSET_FILE_METADATA = 4
    SLOT_OFFSET_PATH_METADATA = 5
    SLOT_IMAGE_FIELD_COUNT_V1 = 3
    SLOT_IMAGE_FIELD_COUNT = 6
    
    def settings(self):
        """Return the settings array in a consistent order"""
        varlist = range(self.SLOT_FIRST_IMAGE + \
                        self.SLOT_IMAGE_FIELD_COUNT * len(self.images))
        varlist[self.SLOT_FILE_TYPE]              = self.file_types
        varlist[self.SLOT_MATCH_METHOD]           = self.match_method
        varlist[self.SLOT_ORDER_GROUP_SIZE]       = self.order_group_size
        varlist[self.SLOT_EXCLUDE]                = self.exclude
        varlist[self.SLOT_MATCH_EXCLUDE]          = self.match_exclude
        varlist[self.SLOT_DESCEND_SUBDIRECTORIES] = self.descend_subdirectories
        varlist[self.SLOT_LOCATION]               = self.location
        varlist[self.SLOT_LOCATION_OTHER]         = self.location_other
        varlist[self.SLOT_CHECK_IMAGES]           = self.check_images
        varlist[self.SLOT_GROUP_BY_METADATA]      = self.group_by_metadata
        varlist[self.SLOT_GROUP_FIELDS]           = self.metadata_fields
        for i in range(len(self.images)):
            ioff = i*self.SLOT_IMAGE_FIELD_COUNT + self.SLOT_FIRST_IMAGE
            varlist[ioff+self.SLOT_OFFSET_COMMON_TEXT] = \
                self.images[i][FD_COMMON_TEXT]
            varlist[ioff+self.SLOT_OFFSET_IMAGE_NAME] = \
                self.images[i][FD_IMAGE_NAME]
            varlist[ioff+self.SLOT_OFFSET_ORDER_POSITION] = \
                self.images[i][FD_ORDER_POSITION]
            varlist[ioff+self.SLOT_OFFSET_METADATA_CHOICE] = \
                self.images[i][FD_METADATA_CHOICE]
            varlist[ioff+self.SLOT_OFFSET_FILE_METADATA] =\
                self.images[i][FD_FILE_METADATA]
            varlist[ioff+self.SLOT_OFFSET_PATH_METADATA] =\
                self.images[i][FD_PATH_METADATA]
        return varlist
    
    def prepare_settings(self, setting_values):
        #
        # Figure out how many images are in the saved settings - make sure
        # the array size matches the incoming #
        #
        assert (len(setting_values) - self.SLOT_FIRST_IMAGE) % self.SLOT_IMAGE_FIELD_COUNT == 0
        image_count = (len(setting_values) - self.SLOT_FIRST_IMAGE) / self.SLOT_IMAGE_FIELD_COUNT
        while len(self.images) > image_count:
            self.remove_imagecb(self.image_keys[0])
        while len(self.images) < image_count:
            self.add_imagecb()
    

    def upgrade_settings(self, setting_values, variable_revision_number, module_name, from_matlab):

        #
        # historic rewrites from CP1.0
        # 
        def upgrade_1_to_2(setting_values):
            """Upgrade rev 1 LoadImages to rev 2

            Handle movie formats new to rev 2
            """
            new_values = list(setting_values[:10])
            image_or_movie =  setting_values[10]
            if image_or_movie == 'Image':
                new_values.append('individual images')
            elif setting_values[11] == 'avi':
                new_values.append('avi movies')
            elif setting_values[11] == 'stk':
                new_values.append('stk movies')
            else:
                raise ValueError('Unhandled movie type: %s'%(setting_values[11]))
            new_values.extend(setting_values[12:])
            return (new_values,2)

        def upgrade_2_to_3(setting_values):
            """Added binary/grayscale question"""
            new_values = list(setting_values)
            new_values.append('grayscale')
            new_values.append('')
            return (new_values,3)

        def upgrade_3_to_4(setting_values):
            """Added text exclusion at slot # 10"""
            new_values = list(setting_values)
            new_values.insert(10,cps.DO_NOT_USE)
            return (new_values,4)

        def upgrade_4_to_5(setting_values):
            new_values = list(setting_values)
            new_values.append(cps.NO)
            return (new_values,5)

        def upgrade_5_to_new_1(setting_values):
            """Take the old LoadImages values and put them in the correct slots"""
            new_values = range(self.SLOT_FIRST_IMAGE_V1)
            new_values[self.SLOT_FILE_TYPE]              = setting_values[11]
            new_values[self.SLOT_MATCH_METHOD]           = setting_values[0]
            new_values[self.SLOT_ORDER_GROUP_SIZE]       = setting_values[9]
            new_values[self.SLOT_MATCH_EXCLUDE]          = setting_values[10]
            new_values[self.SLOT_DESCEND_SUBDIRECTORIES] = setting_values[12]
            new_values[self.SLOT_CHECK_IMAGES]           = setting_values[16]
            loc = setting_values[13]
            if loc == '.':
                new_values[self.SLOT_LOCATION]           = DIR_DEFAULT_IMAGE
            elif loc == '&':
                new_values[self.SLOT_LOCATION]           = DIR_DEFAULT_OUTPUT
            else:
                new_values[self.SLOT_LOCATION]           = DIR_OTHER 
            new_values[self.SLOT_LOCATION_OTHER]         = loc 
            for i in range(0,4):
                text_to_find = setting_values[i*2+1]
                image_name = setting_values[i*2+2]
                if text_to_find == cps.DO_NOT_USE or \
                   image_name == cps.DO_NOT_USE or\
                   text_to_find == '/' or\
                   image_name == '/' or\
                   text_to_find == '\\' or\
                   image_name == '\\':
                    break
                new_values.extend([text_to_find,image_name,text_to_find])
            return (new_values,1)

        #
        # New revisions in CP2.0
        #
        def upgrade_new_1_to_2(setting_values):
            """Add the metadata slots to the images"""
            new_values = list(setting_values[:self.SLOT_FIRST_IMAGE_V1])
            new_values.append(cps.NO) # Group by metadata is off
            for i in range((len(setting_values)-self.SLOT_FIRST_IMAGE_V1) / self.SLOT_IMAGE_FIELD_COUNT_V1):
                off = self.SLOT_FIRST_IMAGE_V1 + i * self.SLOT_IMAGE_FIELD_COUNT_V1
                new_values.extend([setting_values[off],
                                   setting_values[off+1],
                                   setting_values[off+2],
                                   M_NONE,
                                   "None",
                                   "None"])
            return (new_values, 2)

        def upgrade_new_2_to_3(setting_values):
            """Add the checkbox for excluding certain files"""
            new_values = list(setting_values[:self.SLOT_FIRST_IMAGE_V2])
            if setting_values[self.SLOT_MATCH_EXCLUDE] == cps.DO_NOT_USE:
                new_values += [cps.NO]
            else:
                new_values += [cps.YES]
            for i in range((len(setting_values)-self.SLOT_FIRST_IMAGE_V2) / self.SLOT_IMAGE_FIELD_COUNT):
                off = self.SLOT_FIRST_IMAGE_V2 + i * self.SLOT_IMAGE_FIELD_COUNT
                new_values.extend([setting_values[off],
                                   setting_values[off+1],
                                   setting_values[off+2],
                                   M_NONE,
                                   "None",
                                   "None"])
            return (new_values, 3)

        def upgrade_new_3_to_4(setting_values):
            """Add the metadata_fields setting"""
            new_values = list(setting_values[:self.SLOT_FIRST_IMAGE_V3])
            new_values.append('')
            new_values += setting_values[self.SLOT_FIRST_IMAGE_V3:]
            return (new_values, 4)

        if from_matlab:
            if variable_revision_number == 1:
                setting_values,variable_revision_number = upgrade_1_to_2(setting_values)
            if variable_revision_number == 2:
                setting_values,variable_revision_number = upgrade_2_to_3(setting_values)
            if variable_revision_number == 3:
                setting_values,variable_revision_number = upgrade_3_to_4(setting_values)
            if variable_revision_number == 4:
                setting_values,variable_revision_number = upgrade_4_to_5(setting_values)
            if variable_revision_number == 5:
                setting_values,variable_revision_number = upgrade_5_to_new_1(setting_values)
            from_matlab = False
        
        assert not from_matlab
        if variable_revision_number == 1:
            setting_values, variable_revision_number = upgrade_new_1_to_2(setting_values)
        if variable_revision_number == 2:
            setting_values, variable_revision_number = upgrade_new_2_to_3(setting_values)
        if variable_revision_number == 3:
            setting_values, variable_revision_number = upgrade_new_3_to_4(setting_values)

        #
        # Standardize "Default Image Directory" -> "Default Image Folder"
        #
        if setting_values[self.SLOT_LOCATION].startswith("Default Image"):
            setting_values = (setting_values[:self.SLOT_LOCATION] +
                              [DIR_DEFAULT_IMAGE] +
                              setting_values[self.SLOT_LOCATION+1:])
        elif setting_values[self.SLOT_LOCATION].startswith("Default Output"):
            setting_values = (setting_values[:self.SLOT_LOCATION] +
                              [DIR_DEFAULT_OUTPUT] +
                              setting_values[self.SLOT_LOCATION+1:])

        assert variable_revision_number == self.variable_revision_number, "Cannot read version %d of %s"%(variable_revision_number, self.module_name)

        return setting_values, variable_revision_number, from_matlab


    def write_to_handles(self,handles):
        """Write out the module's state to the handles
        
        """
    
    def write_to_text(self,file):
        """Write the module's state, informally, to a text file
        """

    def prepare_run(self, pipeline, image_set_list, frame):
        """Set up all of the image providers inside the image_set_list
        """
        if pipeline.in_batch_mode():
            # Don't set up if we're going to retrieve the image set list
            # from batch mode
            return True
        if self.file_types == FF_OTHER_MOVIES:
            self.prepare_run_of_flex(pipeline, image_set_list)
        elif self.load_movies():
            self.prepare_run_of_movies(pipeline,image_set_list)
        else:
            self.prepare_run_of_images(pipeline, image_set_list, frame)
        return True
    
    def prepare_run_of_images(self, pipeline, image_set_list, frame):
        """Set up image providers for image files"""
        files = self.collect_files()
        if len(files) == 0:
            raise ValueError("CellProfiler did not find any image files that "
                             'matched your matching pattern: "%s"' %
                             self.images[0][FD_COMMON_TEXT])
        
        if (self.group_by_metadata.value and len(self.get_metadata_tags())):
            self.organize_by_metadata(pipeline, image_set_list, files, frame)
        else:
            self.organize_by_order(pipeline, image_set_list, files)
        for name in self.image_name_vars():
            image_set_list.legacy_fields['Pathname%s'%(name.value)]=self.image_directory()

    def organize_by_order(self, pipeline, image_set_list, files):
        """Organize each kind of file by their lexical order
        
        """
        image_names = self.image_name_vars()
        list_of_lists = [[] for x in image_names]
        for pathname,image_index in files:
            list_of_lists[image_index].append(pathname)
        
        image_set_count = len(list_of_lists[0])
        for x,name in zip(list_of_lists[1:],image_names[1:]):
            if len(x) != image_set_count:
                raise RuntimeError("Image %s has %d files, but image %s has %d files" %
                                   (image_names[0], image_set_count,
                                    name.value, len(x)))
        list_of_lists = np.array(list_of_lists)
        root = self.image_directory()
        for i in range(0,image_set_count):
            image_set = image_set_list.get_image_set(i)
            for j in range(len(image_names)):
                self.save_image_set_info(image_set, image_names[j].value,
                                         P_IMAGES, V_IMAGES, 
                                         root, list_of_lists[j,i])
    
    def organize_by_metadata(self, pipeline, image_set_list, files, frame):
        """Organize each kind of file by metadata
        
        """
        #
        # Distribute files according to metadata tags. Each image_name
        # potentially has a subset of the total list of tags. For images
        # without the complete list of tags, we give the image a wildcard
        # for the metadata item that matches everything.
        #
        tags = self.get_metadata_tags()
        #
        # files_by_image_name holds one list of files for each image name index
        #
        files_by_image_name = [[] for i in range(len(self.images))]
        for file,i in files:
            files_by_image_name[i].append(os.path.split(file))
        #
        # Create a monster dictionary tree for each image describing the
        # metadata for each tag. Give a file a metadata value of None
        # if it has no value for a given metadata tag
        #
        d = [{} for i in range(len(self.images))]
        conflicts = []
        for i in range(len(self.images)):
            fd = self.images[i]
            for path, filename in files_by_image_name[i]:
                metadata = self.get_filename_metadata(fd, filename, path)
                parent = d[i]
                for tag in tags[:-1]:
                    value = metadata.get(tag)
                    if parent.has_key(value):
                        child = parent[value]
                    else:
                        child = {}
                        parent[value] = child
                    parent = child
                    last_value = value
                tag = tags[-1]
                value = metadata.get(tag)
                if parent.has_key(value):
                    # There's already a match to this metadata
                    conflict = [fd, parent[value], (path,filename)]
                    conflicts.append(conflict)
                    if not self.check_images:
                        #
                        # Disambiguate conflicts by picking the most recently
                        # modified file.
                        #
                        old_path, old_filename = parent[value]
                        old_stat = os.stat(os.path.join(self.image_directory(),
                                                        old_path, old_filename))
                        old_time = old_stat.st_mtime
                        new_stat = os.stat(os.path.join(self.image_directory(),
                                                        path, filename))
                        new_time = new_stat.st_mtime
                        if new_time > old_time:
                            parent[value] = (path, filename)
                else:
                    parent[value] = (path, filename)
        image_sets = self.get_image_sets(d)
        missing_images = [image_set for image_set in image_sets
                          if None in image_set[1]]
        image_sets = [image_set for image_set in image_sets
                      if not None in image_set[1]]
        #
        # Handle errors, raising an exception if the user wants to check images
        #
        if len(conflicts) or len(missing_images):
            if frame:
                self.report_errors(conflicts, missing_images, frame)
            if self.check_images.value:
                message=""
                if len(conflicts):
                    message +="Conflicts found:\n" 
                    for conflict in conflicts:
                        metadata = self.get_filename_metadata(conflict[0], 
                                                              conflict[1][1], 
                                                              conflict[1][0])
                        message+=("Metadata: %s, First path: %s, First filename: %s, Second path: %s, Second filename: %s\n"%
                                  (str(metadata), conflict[1][0],conflict[1][1],
                                   conflict[2][0],conflict[2][1]))
                if len(missing_images):
                    message += "Missing images:\n"
                    for mi in missing_images:
                        for i in range(len(self.images)):
                            fd = self.images[i]
                            if mi[1][i] is None:
                                message += ("%s: missing " %
                                            (fd[FD_IMAGE_NAME].value))
                            else:
                                message += ("%s: path=%s, file=%s" %
                                            (fd[FD_IMAGE_NAME].value,
                                             mi[1][i][0],mi[1][i][1]))
                raise ValueError(message)
                
        root = self.image_directory()
        for image_set in image_sets:
            keys = {}
            for tag,value in zip(tags,image_set[0]):
                keys[tag] = value
            cpimageset = image_set_list.get_image_set(keys)
            for i in range(len(self.images)):
                path = os.path.join(image_set[1][i][0],image_set[1][i][1])
                self.save_image_set_info(cpimageset,
                                         self.images[i][FD_IMAGE_NAME].value,
                                          P_IMAGES, V_IMAGES, root,path)
    
    def get_dictionary(self, image_set):
        '''Get the module's legacy fields dictionary for this image set'''
        key = "%s:%d"%(self.module_name, self.module_num)
        if not image_set.legacy_fields.has_key(key):
            image_set.legacy_fields[key] = {}
        d = image_set.legacy_fields[key]
        if not d.has_key(image_set.number):
            d[image_set.number] = {}
        return d[image_set.number]
    
    def save_image_set_info(self, image_set, image_name, provider, 
                            version, *args):
        '''Write out the details for creating an image provider
        
        Write information to the image set list legacy fields for saving
        the state needed to create an image provider.
        
        image_set - create a provider on this image set
        image_name - the image name for the image
        provider - the name of an image set provider (the name will be read
                   by load_image_set_info to create the actual provider)
        version - the version # of the provider, in case the arguments change
        args - string arguments that will be passed to the provider's init fn
        '''
        if provider == P_MOVIES:
            raise NotImplementedError("Movie processing has not yet been implemented on the cluster")
        d = self.get_dictionary(image_set)
        d[image_name] = [provider, version] + list(args)
    
    def modify_image_set_info(self, image_set, fn_alter_path):
        '''Redirect path names to a remote host
        
        image_set - modify path names for this image set
        fn_alter_path - call this to modify each path name
        '''
        d = self.get_dictionary(image_set)
        for image_name in d.keys():
            values = d[image_name]
            provider, version = values[:2]
            if provider == P_IMAGES:
                assert version == V_IMAGES
                for i in range(2,4):
                    values[i] = fn_alter_path(values[i])
            else:
                raise NotImplementedError("%s not handled by modify_image_set_info"%provider)
            
    def load_image_set_info(self, image_set):
        '''Load the image set information, creating the providers'''
        assert isinstance(image_set, cpimage.ImageSet)
        d = self.get_dictionary(image_set)
        for image_name in d.keys():
            values = d[image_name]
            provider, version = values[:2]
            if provider == P_IMAGES:
                if version != V_IMAGES:
                    raise NotImplementedError("Can't restore file information: file image provider version %d not supported"%version)
                pathname, filename = values[2:]
                p = LoadImagesImageProvider(image_name, pathname, filename)
            elif provider == P_MOVIES:
                if version != V_MOVIES:
                    raise NotImplementedError("Can't restore file information: file image provider version %d not supported"%version)
                pathname, frame = values[2:]
                path,filename = os.path.split(pathname)
                if self.file_types == FF_STK_MOVIES:
                    p = LoadImagesSTKFrameProvider(image_name, path, filename,
                                                   frame)
                elif self.file_types == FF_AVI_MOVIES:
                    p = LoadImagesMovieFrameProvider(image_name, path, filename,
                                                     int(frame))
                else:
                    raise NotImplementedError("File type %s not supported"%self.file_types.value)
            elif provider == P_FLEX:
                if version != V_FLEX:
                    raise NotImplementedError("Can't restore file information: flex image provider versino %d not supported"%version)
                pathname, channel, z, t, series = values[2:]
                path, filename = os.path.split(pathname)
                p = LoadImagesFlexFrameProvider(image_name, path, filename, 
                                                int(channel), int(z), int(t), int(series))
            else:
                raise NotImplementedError("Can't restore file information: provider %s not supported"%provider)
            image_set.providers.append(p)
    
    def get_image_sets(self, d):
        """Get image sets from a dictionary tree
        
        d - one dictionary tree per image.
        returns a list of tuples. The first element contains a tuple of
        metadata values and the second element contains a list of
        (path,filename) tuples for each image (or are None for errors where 
        there is no metadata match).
        """
        
        if not any([isinstance(dd,dict) for dd in d]):
            # This is a leaf if no elements are dictionaries
            return [(tuple(), d)]
        #
        # Get each represented value for this slot
        #
        values = set()
        for dd in d:
            if not dd is None:
                values.update([x for x in dd.keys() if x is not None])
        result = []
        for value in sorted(values):
            subgroup = tuple((dd and dd.has_key(None) and dd[None]) or # wildcard metadata
                             (dd and dd.get(value)) or                 # fetch subvalue or None if missing
                             None                                      # metadata is missing
                             for dd in d)
            subsets = self.get_image_sets(subgroup)
            for subset in subsets:
                # prepend the current key to the tuple of keys and 
                # duplicate the filename tuple
                subset = ((value,)+subset[0], subset[1])
                result.append(subset)
        return result

    def report_errors(self, conflicts, missing_images, frame):
        """Create an error report window
        
        conflicts: 3-tuple of file dictionary, first path/file and second path/file
                   for two images with the same metadata
        missing_images: two-tuple of metadata keys and the file tuples
                        where at least one of the file tuples is None indicating
                        a missing image
        frame: the parent for the error report
        """
        my_frame = wx.Frame(frame, title="Load images: Error report",
                            size=(600,800),
                            pos =(frame.Position[0],
                                  frame.Position[1]+frame.Size[1]))
        my_frame.Icon = frame.Icon
        panel = wx.Panel(my_frame)
        uber_sizer = wx.BoxSizer()
        my_frame.SetSizer(uber_sizer)
        uber_sizer.Add(panel,1,wx.EXPAND)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)
        font = wx.Font(16,wx.FONTFAMILY_SWISS,wx.FONTSTYLE_NORMAL,
                       wx.FONTWEIGHT_BOLD)
        tags = self.get_metadata_tags()
        tag_ct = len(tags)
        tables = []
        if len(conflicts):
            title = wx.StaticText(panel,
                                  label="Conflicts (two files with same metadata)")
            title.Font = font
            sizer.Add(title, 0, wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL|wx.ALL,3)
            table = wx.ListCtrl(panel,style=wx.LC_REPORT)
            tables.append(table)
            sizer.Add(table, 1, wx.EXPAND|wx.ALL,3)
            for tag, index in zip(tags,range(tag_ct)):
                table.InsertColumn(index,tag)
            table.InsertColumn(index+1,"First path")
            table.InsertColumn(index+2,"First file name")
            table.InsertColumn(index+3,"Second path")
            table.InsertColumn(index+4,"Second file name")
            for conflict in conflicts:
                metadata = self.get_filename_metadata(conflict[0], 
                                                      conflict[1][1], 
                                                      conflict[1][0])
                row = [metadata.get(tag) or "-" for tag in tags]
                row.extend([conflict[1][0],conflict[1][1],
                            conflict[2][0],conflict[2][1]])
                table.Append(row)

        if len(missing_images):
            title = wx.StaticText(panel,
                                  label="Missing images")
            title.Font = font
            sizer.Add(title, 0, wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL|wx.ALL,3)
            table = wx.ListCtrl(panel,style=wx.LC_REPORT)
            tables.append(table)
            sizer.Add(table, 1, wx.EXPAND|wx.ALL,3)
            for tag, index in zip(tags,range(tag_ct)):
                table.InsertColumn(index,tag)
            for fd,index in zip(self.images,range(len(self.images))):
                table.InsertColumn(index*2+tag_ct,
                                   "%s path"%(fd[FD_IMAGE_NAME].value))
                table.InsertColumn(index*2+1+tag_ct,
                                   "%s filename"%(fd[FD_IMAGE_NAME].value))
            for metadata,files_and_paths in missing_images:
                row = list(metadata)
                for file_and_path in files_and_paths:
                    if file_and_path is None:
                        row.extend(["missing","missing"])
                    else:
                        row.extend(file_and_path)
                table.Append(row)
        best_total_width = 0
        for table in tables:
            total_width = 0
            dc=wx.ClientDC(table)
            dc.Font = table.Font
            try:
                for col in range(table.ColumnCount):
                    text = table.GetColumn(col).Text
                    width = dc.GetTextExtent(text)[0]
                    for row in range(table.ItemCount):
                        text = table.GetItem(row,col).Text
                        width = max(width, dc.GetTextExtent(text)[0])
                    width += 16
                    table.SetColumnWidth(col, width)
                    total_width += width+4
            finally:
                dc.Destroy()
            best_total_width = max(best_total_width, total_width)
        table.SetMinSize((best_total_width, table.GetMinHeight()))
        my_frame.Fit()
        my_frame.Show()
    
    def prepare_run_of_flex(self, pipeline, image_set_list):
        '''Set up image providers for flex files'''
        files = self.collect_files()
        if len(files) == 0:
            raise ValueError("there are no image files in the chosen folder (or subfolders, if you requested them to be analyzed as well)")
        root = self.image_directory()
        image_names = self.image_name_vars()
        #
        # The list of lists has one list per image type. Each per-image type
        # list is composed of tuples of pathname and frame #
        #
        image_set_count = 0
        for pathname,image_index in files:
            pathname = os.path.join(self.image_directory(), pathname)
            formatreader.jutil.attach()
            path, filename = os.path.split(pathname)
            metadata = self.get_filename_metadata(self.images[0], filename, path)
            try:
                rdr = ImageReader()
                rdr.setId(pathname)
                print "%s has %d series"%(pathname, rdr.getSeriesCount())
                for i in range(rdr.getSeriesCount()):
                    rdr.setSeries(i)
                    print "%s - series %d: %d channels, %d z, %d t"%(pathname, i, rdr.getSizeC(), rdr.getSizeZ(), rdr.getSizeT())
                    for z in range(rdr.getSizeZ()):
                        for t in range(rdr.getSizeT()):
                            if self.group_by_metadata:
                                key = metadata.copy()
                                key[M_Z] = str(z)
                                key[M_T] = str(t)
                                key[M_SERIES] = str(i)
                                image_set = image_set_list.get_image_set(key)
                            else:
                                image_set = image_set_list.get_image_set(image_set_count)
                            d = self.get_dictionary(image_set)
                            for c,image_name in enumerate(image_names):
                                d[image_name.value] = (P_FLEX, V_FLEX, pathname, c, z, t, i)
                            image_set_count += 1
            finally:
                formatreader.jutil.detach()
        
    def prepare_run_of_movies(self, pipeline, image_set_list):
        """Set up image providers for movie files"""
        files = self.collect_files()
        if len(files) == 0:
            raise ValueError("there are no image files in the chosen folder (or subfolders, if you requested them to be analyzed as well)")
        
        root = self.image_directory()
        image_names = self.image_name_vars()
        #
        # The list of lists has one list per image type. Each per-image type
        # list is composed of tuples of pathname and frame #
        #
        list_of_lists = [[] for x in image_names]
        for pathname,image_index in files:
            pathname = os.path.join(self.image_directory(), pathname)
            frame_count = self.get_frame_count(pathname)
            if frame_count == 0:
                print "Warning - no frame count detected"
                frame_count = 256
            for i in range(frame_count):
                list_of_lists[image_index].append((pathname,i))
        image_set_count = len(list_of_lists[0])
        for x,name in zip(list_of_lists[1:],image_names):
            if len(x) != image_set_count:
                raise RuntimeError("Image %s has %d frames, but image %s has %d frames"%(image_names[0],image_set_count,name.value,len(x)))
        list_of_lists = np.array(list_of_lists,dtype=object)
        for i in range(0,image_set_count):
            image_set = image_set_list.get_image_set(i)
            d = self.get_dictionary(image_set)
            for name, (file, frame) \
                in zip(image_names, list_of_lists[:,i]):
                d[name.value] = (P_MOVIES, V_MOVIES, file, frame)
        for name in image_names:
            image_set_list.legacy_fields['Pathname%s'%(name.value)]=root
    
    def prepare_to_create_batch(self, pipeline, image_set_list, fn_alter_path):
        '''Prepare to create a batch file
        
        This function is called when CellProfiler is about to create a
        file for batch processing. It will pickle the image set list's
        "legacy_fields" dictionary. This callback lets a module prepare for
        saving.
        
        pipeline - the pipeline to be saved
        image_set_list - the image set list to be saved
        fn_alter_path - this is a function that takes a pathname on the local
                        host and returns a pathname on the remote host. It
                        handles issues such as replacing backslashes and
                        mapping mountpoints. It should be called for every
                        pathname stored in the settings or legacy fields.
        '''
        for i in range(image_set_list.count()):
            image_set = image_set_list.get_image_set(i)
            self.modify_image_set_info(image_set, fn_alter_path)
        self.location_other.value = fn_alter_path(self.location_other.value)
        return True
    
    def prepare_group(self, pipeline, image_set_list, grouping,
                      image_numbers):
        '''Load the images from the dictionary into the image sets here'''
        for image_number in image_numbers:
            image_set = image_set_list.get_image_set(image_number-1)
            self.load_image_set_info(image_set)
            
    def is_interactive(self):
        return False

    def run(self,workspace):
        """Run the module - add the measurements
        
        """
        if self.file_types in (FF_AVI_MOVIES, FF_STK_MOVIES):
            header = ["Image name", "Path", "Filename","Frame"]
            ratio = [1.0,2.5,2.0,0.5]
        else:
            header = ["Image name","Path","Filename"]
            ratio = [1.0,3.0,2.0]
        tags = self.get_metadata_tags()
        ratio += [1.0 for tag in tags]
        ratio = [x / sum(ratio) for x in ratio]
        header += tags 
        statistics = [header]
        m = workspace.measurements
        image_set_metadata = {}
        do_flex = (self.file_types == FF_OTHER_MOVIES)
        if do_flex:
            provider = workspace.image_set.get_image_provider(self.images[0][FD_IMAGE_NAME].value)
            for tag, value in ((M_Z, provider.get_z()),
                               (M_T, provider.get_t()),
                               (M_SERIES, provider.get_series())):
                m.add_image_measurement("Metadata_"+tag, value)
                image_set_metadata[tag] = value
        for fd in self.images:
            provider = workspace.image_set.get_image_provider(fd[FD_IMAGE_NAME].value)
            path, filename = os.path.split(provider.get_filename())
            name = provider.name
            if self.file_types in (FF_AVI_MOVIES, FF_STK_MOVIES):
                row = [name, path, filename, provider.get_frame()]
            else:
                row = [name, path, filename]
            metadata = self.get_filename_metadata(self.images[0] if do_flex 
                                                  else fd, filename, path)
            m.add_measurement('Image','FileName_'+name, filename)
            full_path = os.path.join(self.image_directory(),path)
            m.add_measurement('Image','PathName_'+name, full_path)
            pixel_data = provider.provide_image(workspace.image_set).pixel_data
            digest = hashlib.md5()
            digest.update(np.ascontiguousarray(pixel_data).data)
            m.add_measurement('Image','MD5Digest_'+name, digest.hexdigest())
            for key in metadata:
                measurement = 'Metadata_%s'%(key)
                if not m.has_current_measurements('Image',measurement):
                    m.add_measurement('Image',measurement,metadata[key])
                elif metadata[key] != m.get_current_measurement('Image',measurement):
                    raise ValueError("Image set has conflicting %s metadata: %s vs %s"%
                                     (key, metadata[key], 
                                      m.get_current_measurement('Image',measurement)))
            for tag in tags:
                if metadata.has_key(tag):
                    row.append(metadata[tag])
                elif image_set_metadata.has_key(tag):
                    row.append(image_set_metadata[tag])
                else:
                    row.append("")
            statistics.append(row)
        workspace.display_data.statistics = statistics
        workspace.display_data.ratio = ratio

    def display(self, workspace):
        if workspace.frame != None:
            figure = workspace.create_or_find_figure(title="Load images, image set #%d"%(
                workspace.measurements.image_set_number),
                                                 subplots=(1,1))
            figure.subplot_table(0,0,workspace.display_data.statistics,
                             ratio=workspace.display_data.ratio)

    def get_filename_metadata(self, fd, filename, path):
        """Get the filename and path metadata for a given image
        
        fd - file/image dictionary
        filename - filename to be parsed
        path - path to be parsed
        """
        metadata = {}
        if fd[FD_METADATA_CHOICE].value in (M_BOTH, M_FILE_NAME):
            metadata.update(cpm.extract_metadata(fd[FD_FILE_METADATA].value,
                                                 filename))
        if fd[FD_METADATA_CHOICE].value in (M_BOTH, M_PATH):
            path = os.path.abspath(path)
            metadata.update(cpm.extract_metadata(fd[FD_PATH_METADATA].value,
                                                 path))
        if needs_well_metadata(metadata.keys()):
            well_row_token, well_column_token = well_metadata_tokens(metadata.keys())
            metadata[cpm.FTR_WELL] = (metadata[well_row_token] + 
                                      metadata[well_column_token])
        return metadata
        
    def get_frame_count(self, pathname):
        """Return the # of frames in a movie"""
        if self.file_types in (FF_AVI_MOVIES,FF_OTHER_MOVIES,FF_STK_MOVIES):
            formatreader.jutil.attach()
            try:
                rdr = ImageReader()
                rdr.setId(pathname)
                if self.file_types == FF_STK_MOVIES:
                    return rdr.getSizeT()
                else:
                    return rdr.getSizeT()
            finally:
                formatreader.jutil.detach()
            
        raise NotImplementedError("get_frame_count not implemented for %s"%(self.file_types))

    def get_metadata_tags(self, fd=None):
        """Find the metadata tags for the indexed image

        fd - an image file directory from self.images
        """
        if not fd:
            s = set()
            for fd in self.images:
                s.update(self.get_metadata_tags(fd))
            tags = list(s)
            tags.sort()
            return tags
        
        tags = []
        if fd[FD_METADATA_CHOICE] in (M_FILE_NAME, M_BOTH):
            tags += cpm.find_metadata_tokens(fd[FD_FILE_METADATA].value)
        if fd[FD_METADATA_CHOICE] in (M_PATH, M_BOTH):
            tags += cpm.find_metadata_tokens(fd[FD_PATH_METADATA].value)
        if self.file_types == FF_OTHER_MOVIES:
            tags += [M_Z, M_T, M_SERIES]
        if needs_well_metadata(tags):
            tags += [cpm.FTR_WELL]
        return tags
    
    def get_groupings(self, image_set_list):
        '''Return the groupings as indicated by the metadata_fields setting'''
        if self.group_by_metadata.value:
            keys = self.metadata_fields.selections
            if len(keys) == 0:
                return None
            return image_set_list.get_groupings(keys)
        else:
            return None
    
    def load_images(self):
        """Return true if we're loading images
        """
        return self.file_types == FF_INDIVIDUAL_IMAGES
    
    def load_movies(self):
        """Return true if we're loading movies
        """
        return self.file_types != FF_INDIVIDUAL_IMAGES
    
    def load_choice(self):
        """Return the way to match against files: MS_EXACT_MATCH, MS_REGULAR_EXPRESSIONS or MS_ORDER
        """
        return self.match_method.value
    
    def analyze_sub_dirs(self):
        """Return True if we should analyze subdirectories in addition to the root image directory
        """
        return self.descend_subdirectories.value
    
    def collect_files(self, dirs=[]):
        """Collect the files that match the filter criteria
        
        Collect the files that match the filter criteria, starting at the image directory
        and descending downward if AnalyzeSubDirs allows it.
        dirs - a list of subdirectories connecting the image directory to the
               directory currently being searched
        Returns a list of two-tuples where the first element of the tuple is the path
        from the root directory, including the file name, the second element is the
        index within the image settings (e.g. ImageNameVars).
        """
        path = reduce(os.path.join, dirs, self.image_directory() )
        files = os.listdir(path)
        files.sort()
        isdir = lambda x: os.path.isdir(os.path.join(path,x))
        isfile = lambda x: os.path.isfile(os.path.join(path,x))
        subdirs = filter(isdir, files)
        files = filter(isfile,files)
        path_to = (len(dirs) and reduce(os.path.join, dirs)) or ''
        files = [(os.path.join(path_to,file), self.filter_filename(file)) for file in files]
        files = filter(lambda x: x[1] != None,files)
        if self.analyze_sub_dirs():
            for dir in subdirs:
                files += self.collect_files(dirs + [dir])
        return files
        
    def image_directory(self):
        """Return the image directory
        """
        if self.location == DIR_DEFAULT_IMAGE:
            return preferences.get_default_image_directory()
        elif self.location == DIR_DEFAULT_OUTPUT:
            return preferences.get_default_output_directory()
        else:
            return preferences.get_absolute_path(self.location_other.value)
    
    def image_name_vars(self):
        """Return the list of values in the image name field (the name that later modules see)
        """
        return [fd[FD_IMAGE_NAME] for fd in self.images]
        
    def text_to_find_vars(self):
        """Return the list of values in the image name field (the name that later modules see)
        """
        if self.file_types == FF_OTHER_MOVIES:
            # Return only the first text to find for .flex files
            return [self.images[0][FD_COMMON_TEXT]]
        return [fd[FD_COMMON_TEXT] for fd in self.images]
    
    def text_to_exclude(self):
        """Return the text to match against the file name to exclude it from the set
        """
        return self.match_exclude.value
    
    def filter_filename(self, filename):
        """Returns either None or the index of the match setting
        """
        if not is_image(filename):
            return None
        if ((True and is_movie(filename)) != 
            (True and (self.file_types in (FF_AVI_MOVIES, FF_STK_MOVIES, 
                                           FF_OTHER_MOVIES)))):
            return None
                                                    
        if self.text_to_exclude() != cps.DO_NOT_USE and \
            filename.find(self.text_to_exclude()) >=0:
            return None
        if self.load_choice() == MS_EXACT_MATCH:
            ttfs = self.text_to_find_vars()
            for i,ttf in enumerate(ttfs):
                if filename.find(ttf.value) >=0:
                    return i
        elif self.load_choice() == MS_REGEXP:
            ttfs = self.text_to_find_vars()
            for i,ttf in enumerate(ttfs):
                if re.search(ttf.value, filename):
                    return i
        else:
            raise NotImplementedError("Load by order not implemented")
        return None

    def get_measurement_columns(self, pipeline):
        '''Return a sequence describing the measurement columns needed by this module 
        '''
        cols = []
        for fd in self.images:
            name = fd[FD_IMAGE_NAME].value
            cols += [(cpm.IMAGE, 'FileName_'+name, cpm.COLTYPE_VARCHAR_FILE_NAME)]
            cols += [(cpm.IMAGE, 'PathName_'+name, cpm.COLTYPE_VARCHAR_PATH_NAME)]
            cols += [(cpm.IMAGE, 'MD5Digest_'+name, cpm.COLTYPE_VARCHAR_FORMAT%32)]
        
        fd = self.images[0]
        all_tokens = []
        if fd[FD_METADATA_CHOICE]==M_FILE_NAME or fd[FD_METADATA_CHOICE]==M_BOTH:
            tokens = cpm.find_metadata_tokens(fd[FD_FILE_METADATA].value)
            cols += [(cpm.IMAGE, '_'.join((cpm.C_METADATA, token)), 
                      cpm.COLTYPE_VARCHAR_FILE_NAME) for token in tokens]
            all_tokens += tokens
        
        if fd[FD_METADATA_CHOICE]==M_PATH or fd[FD_METADATA_CHOICE]==M_BOTH:
            tokens = cpm.find_metadata_tokens(fd[FD_PATH_METADATA].value)
            all_tokens += tokens
            cols += [(cpm.IMAGE, '_'.join((cpm.C_METADATA,token)), 
                      cpm.COLTYPE_VARCHAR_PATH_NAME) for token in tokens]
        #
        # Add a well feature if we have well row and well column
        #
        if needs_well_metadata(all_tokens):
            cols += [(cpm.IMAGE, '_'.join((cpm.C_METADATA, cpm.FTR_WELL)),
                      cpm.COLTYPE_VARCHAR_FILE_NAME)]
        if self.file_types == FF_OTHER_MOVIES:
            cols += [(cpm.IMAGE, M_Z, cpm.COLTYPE_INTEGER),
                     (cpm.IMAGE, M_T, cpm.COLTYPE_INTEGER),
                     (cpm.IMAGE, M_SERIES, cpm.COLTYPE_INTEGER)]
        return cols
    
    def change_causes_prepare_run(self, setting):
        '''Check to see if changing the given setting means you have to restart
        
        Some settings, esp in modules like LoadImages, affect more than
        the current image set when changed. For instance, if you change
        the name specification for files, you have to reload your image_set_list.
        Override this and return True if changing the given setting means
        that you'll have to do "prepare_run".
        '''
        #
        # It's safest to say that any change in loadimages requires a restart
        #
        return True
            
def well_metadata_tokens(tokens):
    '''Return the well row and well column tokens out of a set of metadata tokens'''

    well_row_token = None
    well_column_token = None
    for token in tokens:
        if cpm.is_well_row_token(token):
            well_row_token = token
        if cpm.is_well_column_token(token):
            well_column_token = token
    return well_row_token, well_column_token

def needs_well_metadata(tokens):
    '''Return true if, based on a set of metadata tokens, we need a well token
    
    Check for a row and column token and the absence of the well token.
    '''
    if cpm.FTR_WELL.lower() in [x.lower() for x in tokens]:
        return False
    well_row_token, well_column_token = well_metadata_tokens(tokens)
    return (well_row_token is not None) and (well_column_token is not None)
    
def is_image(filename):
    '''Determine if a filename is a potential image file based on extension'''
    ext = os.path.splitext(filename)[1].lower()
    if PILImage.EXTENSION.has_key(ext):
        return True
    return ext in ('.avi', '.mpeg', '.mat', '.stk','.flex')

def is_movie(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ('.avi', '.mpeg', '.stk','.flex')


class LoadImagesImageProviderBase(cpimage.AbstractImageProvider):
    '''Base for image providers: handle pathname and filename & URLs'''
    def __init__(self, name, pathname, filename):
        '''Initializer
        
        name - name of image to be provided
        pathname - path to file or base of URL
        filename - filename of file or last chunk of URL
        '''
        self.__name = name
        self.__pathname = pathname
        self.__filename = filename
        self.__cached_file = None
        self.__is_cached = False
        self.__cacheing_tried = False

    def get_name(self):
        return self.__name
    
    def get_pathname(self):
        return self.__pathname
    
    def get_filename(self):
        return self.__filename
    
    def cache_file(self):
        '''Cache a file that needs to be HTTP downloaded'''
        if self.__cacheing_tried:
            return
        self.__cacheing_tried = True
        #
        # Check to see if the pathname can be accessed as a directory
        # If so, handle normally
        #
        if len(self.get_pathname()) == 0 or os.path.exists(self.get_pathname()):
            return
        url = '/'.join((self.get_pathname(), self.get_filename()))
        self.__cached_file, headers = urllib.urlretrieve(url)
        self.__is_cached = True
            
    def get_full_name(self):
        self.cache_file()
        if self.__is_cached:
            return self.__cached_file
        return os.path.join(self.get_pathname(),self.get_filename())
    
    def release_memory(self):
        '''Release any image memory
        
        Possibly delete the temporary file'''
        if self.__is_cached:
            try:
                os.remove(self.__cached_file)
                self.__is_cached = False
                self.__cacheing_tried = False
                self.__cached_file = None
            except:
                traceback.print_exc()
        
class LoadImagesImageProvider(LoadImagesImageProviderBase):
    """Provide an image by filename, loading the file as it is requested
    """
    def __init__(self,name,pathname,filename):
        super(LoadImagesImageProvider, self).__init__(name, pathname, filename)
    
    def provide_image(self, image_set):
        """Load an image from a pathname
        """
        self.cache_file()
        filename = self.get_filename()
        if filename.lower().endswith(".mat"):
            imgdata = scipy.io.matlab.mio.loadmat(self.get_full_name(),
                                                  struct_as_record=True)
            img = imgdata["Image"]
        elif (os.path.splitext(filename.lower())[-1] 
              in USE_BIOFORMATS_FIRST and
              has_bioformats):
            try:
                img = load_using_bioformats(self.get_full_name())
            except:
                traceback.print_exc()
                img = load_using_PIL(self.get_full_name())
        else:
            # try PIL first, for speed
            try:
                img = load_using_PIL(self.get_full_name())
            except:
                if has_bioformats:
                    img = load_using_bioformats(self.get_full_name())
                else:
                    raise
            
        return cpimage.Image(img,
                             path_name = self.get_pathname(),
                             file_name = self.get_filename())
    

def load_using_PIL(path, index=0, seekfn=None):
    '''Get the pixel data for an image using PIL
    
    path - path to file
    index - index of the image if stacked image format such as TIFF
    seekfn - a function for seeking to a given image in a stack
    '''
    if path.lower().endswith(".tif"):
        try:
            img = PILImage.open(path)
        except:
            from contrib.tifffile import TIFFfile
            tiffimg = TIFFfile(str(path))
            img = tiffimg.asarray(squeeze=True)
            if img.dtype == np.uint16:
                img = (img.astype(np.float) - 2**15) / 2**12
            return img
    else:
        img = PILImage.open(path)
    if seekfn is None:
        img.seek(index)
    else:
        seekfn(img, index)
    if img.mode=='I;16':
        # 16-bit image
        # deal with the endianness explicitly... I'm not sure
        # why PIL doesn't get this right.
        imgdata = np.fromstring(img.tostring(),np.uint8)
        imgdata.shape=(int(imgdata.shape[0]/2),2)
        imgdata = imgdata.astype(np.uint16)
        hi,lo = (0,1) if img.tag.prefix == 'MM' else (1,0)
        imgdata = imgdata[:,hi]*256 + imgdata[:,lo]
        img_size = list(img.size)
        img_size.reverse()
        new_img = imgdata.reshape(img_size)
        # The magic # for maximum sample value is 281
        if img.tag.has_key(281):
            img = new_img.astype(float) / img.tag[281][0]
        elif np.max(new_img) < 4096:
            img = new_img.astype(float) / 4095.
        else:
            img = new_img.astype(float) / 65535.
    else:
        # There's an apparent bug in the PIL library that causes
        # images to be loaded upside-down. At best, load and save have opposite
        # orientations; in other words, if you load an image and then save it
        # the resulting saved image will be upside-down
        img = img.transpose(PILImage.FLIP_TOP_BOTTOM)
        img = matplotlib.image.pil_to_array(img)
    return img

def load_using_bioformats(path, c=None, z=0, t=0, series=None):
    '''Load the given image file using the Bioformats library
    
    path: path to the file
    z: the frame index in the z (depth) dimension.
    t: the frame index in the time dimension.
    
    Returns either a 2-d (grayscale) or 3-d (2-d + 3 RGB planes) image
    '''
    #
    # Bioformats is more picky about slashes than Python
    #
    if sys.platform.startswith("win"):
        path = path.replace("/",os.path.sep)
    try:
        formatreader.jutil.attach()
        rdr = ImageReader()
        rdr.setId(path)
        width = rdr.getSizeX()
        height = rdr.getSizeY()
        pixel_type = rdr.getPixelType()
        little_endian = rdr.isLittleEndian()
        if pixel_type == FormatTools.INT8:
            dtype = np.char
            scale = 255
        elif pixel_type == FormatTools.UINT8:
            dtype = np.uint8
            scale = 255
        elif pixel_type == FormatTools.UINT16:
            dtype = '<u2' if little_endian else '>u2'
            scale = 65536
        elif pixel_type == FormatTools.INT16:
            dtype = '<i2' if little_endian else '>i2'
            scale = 65536
        elif pixel_type == FormatTools.UINT32:
            dtype = '<u4' if little_endian else '>u4'
            scale = 2**32
        elif pixel_type == FormatTools.INT32:
            dtype = '<i4' if little_endian else '>i4'
            scale = 2**32
        elif pixel_type == FormatTools.FLOAT:
            dtype = '<f4' if little_endian else '>f4'
            scale = 1
        elif pixel_type == FormatTools.DOUBLE:
            dtype = '<f8' if little_endian else '>f8'
            scale = 1
        max_sample_value = rdr.getMetadataValue('MaxSampleValue')
        if max_sample_value is not None:
            try:
                scale = formatreader.jutil.call(max_sample_value, 
                                                'intValue', '()I')
            except:
                sys.stderr.write("WARNING: failed to get MaxSampleValue for image. Intensities may be improperly scaled\n")
        if series is not None:
            rdr.setSeries(series)
        if rdr.isRGB() and rdr.isInterleaved():
            index = rdr.getIndex(z,0,t)
            image = np.frombuffer(rdr.openBytes(index), dtype)
            image.shape = (height, width, 3)
        elif c is not None:
            index = rdr.getIndex(z,c,t)
            image = np.frombuffer(rdr.openBytes(index), dtype)
            image.shape = (height, width)
        elif rdr.getRGBChannelCount() > 1:
            rdr.close()
            rdr = ChannelSeparator(ImageReader())
            rdr.setId(path)
            red_image, green_image, blue_image = [
                np.frombuffer(rdr.openBytes(rdr.getIndex(z,i,t)),dtype)
                for i in range(3)]
            image = np.dstack((red_image, green_image, blue_image))
            image.shape=(height,width,3)
        else:
            index = rdr.getIndex(z,0,t)
            image = np.frombuffer(rdr.openBytes(index),dtype)
            image.shape = (height,width)
        rdr.close()
        del rdr
        #
        # Run the Java garbage collector here.
        #
        formatreader.jutil.static_call("java/lang/System",
                                       "gc","()V")
        image = image.astype(float) / float(scale)
    finally:
        formatreader.jutil.detach()
    return image
    
class LoadImagesMovieFrameProvider(LoadImagesImageProviderBase):
    """Provide an image by filename:frame, loading the file as it is requested
    """
    def __init__(self,name,pathname,filename,frame):
        super(LoadImagesMovieFrameProvider, self).__init__(name, pathname, filename)
        self.__frame = frame
    
    def provide_image(self, image_set):
        """Load an image from a movie frame
        """
        pixel_data = load_using_bioformats(self.get_full_name(), z=0, 
                                           t=self.__frame)
        image = cpimage.Image(pixel_data, path_name = self.get_pathname(),
                              file_name = self.get_filename())
        return image
    
    def get_frame(self):
        return self.__frame

class LoadImagesFlexFrameProvider(LoadImagesImageProviderBase):
    """Provide an image by filename:frame, loading the file as it is requested
    """
    def __init__(self,name,pathname,filename,channel, z, t, series):
        super(LoadImagesFlexFrameProvider, self).__init__(name, pathname, filename)
        self.__channel = channel
        self.__z = z
        self.__t = t
        self.__series    = series
    
    def provide_image(self, image_set):
        """Load an image from a movie frame
        """
        pixel_data = load_using_bioformats(self.get_full_name(), 
                                           c=self.__channel,
                                           z=self.__z, 
                                           t=self.__t,
                                           series=self.__series)
        image = cpimage.Image(pixel_data, path_name = self.get_pathname(),
                              file_name = self.get_filename())
        return image
    
    def get_c(self):
        '''Get the channel #'''
        return self.__channel
    
    def get_z(self):
        '''Get the z stack #'''
        return self.__z
    
    def get_t(self):
        '''Get the time index'''
        return self.__t
    
    def get_series(self):
        '''Get the series #'''
        return self.__series
    
class LoadImagesSTKFrameProvider(LoadImagesImageProviderBase):
    """Provide an image by filename:frame from an STK file"""
    def __init__(self, name, pathname, filename, frame):
        '''Initialize the provider
        
        name - name of the provider for access from image set
        pathname - path to the file
        filename - name of the file
        frame - # of the frame to provide
        '''
        super(LoadImagesSTKFrameProvider, self).__init__(name, pathname, filename)
        self.__frame    = frame
        
    def provide_image(self, image_set):
        try:
            def seekfn(img, index):
                '''Seek in an STK file to a given stack frame
                
                The stack frames are of constant size and follow each other.
                The tiles contain offsets which need to be incremented by
                the size of a stack frame. The following is from 
                Molecular Devices' STK file format document:
                StripOffsets
                The strips for all the planes of the stack are stored 
                contiguously at this location. The following pseudocode fragment 
                shows how to find the offset of a specified plane planeNum.
                LONG	planeOffset = planeNum *
                    (stripOffsets[stripsPerImage - 1] +
                    stripByteCounts[stripsPerImage - 1] - stripOffsets[0]);
                Note that the planeOffset must be added to the stripOffset[0]
                to find the image data for the specific plane in the file.
                '''
                plane_offset = long(index) * (img.ifd[TIFF.STRIPOFFSETS][-1] +
                                              img.ifd[TIFF.STRIPBYTECOUNTS][-1] -
                                              img.ifd[TIFF.STRIPOFFSETS][0])
                img.tile = [(coding, location, offset+plane_offset, format)
                            for coding, location, offset, format in img.tile]
                
            img = load_using_PIL(self.get_full_name(), self.__frame, seekfn)
        except:
            if has_bioformats:
                img = load_using_bioformats(self.get_full_name(),
                                         t=self.__frame)
            else:
                raise
        return cpimage.Image(img,
                             path_name = self.get_pathname(),
                             file_name = self.get_filename())
    def get_frame(self):
        return self.__frame

