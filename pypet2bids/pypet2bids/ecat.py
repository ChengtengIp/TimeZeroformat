import datetime
import re
import nibabel
import os
import json
import pypet2bids.helper_functions
import tempfile
from pypet2bids.sidecar import sidecar_template_full, sidecar_template_short
from dateutil import parser
from pypet2bids.read_ecat import read_ecat, read_bytes, get_directory_data
from pypet2bids.ecat2nii import ecat2nii
from pypet2bids.helper_functions import get_recon_method

"""
This function does?

:format:
:param:
:return:

Anthony Galassi
-----------------------------
Copyright Open NeuroPET team
"""

def parse_this_date(date_like_object) -> str:
    """
    Uses the dateutil.parser module to extract a date from a variety of differently formatted date strings
    :param date_like_object: something that resembles a timestamp or a date time, could be integer, float, or string.
    :return: an hour minute second datetime string.
    """
    if type(date_like_object) is int:
        parsed_date = datetime.datetime.fromtimestamp(date_like_object)
    else:
        parsed_date = parser.parse(date_like_object)

    return parsed_date.strftime("%H:%M:%S")


class Ecat:
    """
    This class reads an ecat file -> extracts header, subheader, and image matrices for
    viewing in stdout. Additionally, this class can be used to convert an ECAT7.X image into a nifti image.
    """

    def __init__(self, ecat_file, nifti_file=None, decompress=True, collect_pixel_data=True):
        """
        Initialization of this class requires only a path to an ecat file.

        :param ecat_file: path to a valid ecat file
        :param nifti_file: when using this class for conversion from ecat to nifti this path, if supplied, will be used
            to output the nevly generated nifti
        :param decompress: attempt to decompress the ecat file, should probably be set to false
        :param kwargs: used to manually override or insert information into the the nifti sidecare.json.
            Useful for including information that isn't w/ in an ECAT file.
        """
        self.ecat_header = {}  # ecat header information is stored here
        self.subheaders = []  # subheader information is placed here
        self.ecat_info = {}
        self.affine = {}  # affine matrix/information is stored here.
        self.frame_start_times = []  # frame_start_times, frame_durations, and decay_factors are all
        self.frame_durations = []  # extracted from ecat subheaders. They're pretty important and get
        self.decay_factors = []  # stored here
        self.sidecar_template = sidecar_template_full  # bids approved sidecar file with ALL bids fields
        self.sidecar_template_short = sidecar_template_short  # bids approved sidecar with only required bids fields
        self.directory_table = None
        if os.path.isfile(ecat_file):
            self.ecat_file = ecat_file
        else:
            raise FileNotFoundError(ecat_file)

        if '.gz' in self.ecat_file and decompress is True:
            uncompressed_ecat_file = re.sub('.gz', '', self.ecat_file)
            pypet2bids.helper_functions.decompress(self.ecat_file, uncompressed_ecat_file)
            self.ecat_file = uncompressed_ecat_file

        if '.gz' in self.ecat_file and decompress is False:
            raise Exception("Nifti must be decompressed for reading of file headers")

        try:
            self.ecat = nibabel.ecat.load(self.ecat_file)
        except nibabel.filebasedimages.ImageFileError as err:
            print("\nFailed to load ecat image.\n")
            raise err

        directory_byte_block = read_bytes(
            path_to_bytes=self.ecat_file,
            byte_start=512,
            byte_stop=1024)

        self.directory_table = get_directory_data(directory_byte_block, self.ecat_file)

        # extract ecat info
        self.extract_affine()
        if collect_pixel_data:
            self.ecat_header, self.subheaders, self.data = read_ecat(self.ecat_file)
        else:
            self.ecat_header, self.subheaders, self.data = read_ecat(self.ecat_file, collect_pixel_data=False)

        # aggregate ecat info into ecat_info dictionary
        self.ecat_info['header'] = self.ecat_header
        self.ecat_info['subheaders'] = self.subheaders
        self.ecat_info['affine'] = self.affine

        # swap file extensions and save output nifti with same name as original ecat
        if not nifti_file:
            self.nifti_file = os.path.splitext(self.ecat_file)[0] + ".nii"
        else:
            self.nifti_file = nifti_file

    def make_nifti(self, output_path=None):
        """
        Outputs a nifti from the read in ECAT file.

        :param output_path: Optional path to output file to, if not supplied saves nifti in same directory as ECAT
        :return: the output path the nifti was written to, used later for placing metadata/sidecar files
        """

        # save nifti
        if output_path is None:
            output = self.nifti_file
        else:
            output = output_path
        ecat2nii(ecat_main_header=self.ecat_header, ecat_subheaders=self.subheaders, ecat_pixel_data=self.data,
                 nifti_file=output, affine=self.affine)

        return output

    def extract_affine(self):
        """
        Extract affine matrix from ecat
        """
        self.affine = self.ecat.affine.tolist()

    def show_affine(self):
        """
        Display affine to stdout
        :return: affine matrix row by row.
        """
        for row in self.affine:
            print(row)

    def show_directory_table(self):
        """
        Prints the directory table for the ECAT file to stdout.

        :return: None
        """
        for row in range(self.directory_table.shape[0]):
            for column in range(self.directory_table.shape[1]):
                if column == self.directory_table.shape[1] - 1:
                    print(self.directory_table[row][column])
                else:
                    print(self.directory_table[row][column], end=',', sep='')

    def show_header(self):
        """
        Display header to stdout in key: value format.

        :return: None
        """
        for key, value in self.ecat_header.items():
            print(f"{key}: {value}")

    def show_subheaders(self):
        """
        Displays subheaders to stdout.

        :return: None
        """
        for subheader in self.subheaders:
            print(subheader)

    def populate_sidecar(self, **kwargs):
        """
        Creates a side car dictionary with any bids relevant information extracted from the ecat.

        :param kwargs: Populates sidecar file with relevant PET information, additional information that is not in the
            ECAT file can be supplied as a dictionar argument via kwargs.
        :return: None
        """

        # if it's an ecat it's Siemens
        self.sidecar_template['Manufacturer'] = 'Siemens'
        # Siemens model best guess
        self.sidecar_template['ManufacturersModelName'] = self.ecat_header.get('SERIAL_NUMBER', None)
        self.sidecar_template['TracerRadionuclide'] = self.ecat_header.get('ISOTOPE_NAME', None)
        self.sidecar_template['PharmaceuticalName'] = self.ecat_header.get('RADIOPHARAMCEUTICAL', None)

        # collect frame time start and populate various subheader fields
        for subheader in self.subheaders:
            self.sidecar_template['DecayCorrectionFactor'].append(subheader.get('DECAY_CORR_FCTR', None))
            self.sidecar_template['FrameTimesStart'].append(subheader.get('FRAME_START_TIME', None))
            self.sidecar_template['FrameDuration'].append(subheader.get('FRAME_DURATION', None))
            self.sidecar_template['ScaleFactor'].append(subheader.get('SCALE_FACTOR', None))

            # note some of these values won't be in the subheaders for the standard matrix image
            # need to make sure to clean up arrays and fields filled w/ none during pruning
            self.sidecar_template['ScatterFraction'].append(subheader.get('SCATTER_FRACTION', None))
            self.sidecar_template['PromptRate'].append(subheader.get('PROMPT_RATE', None))
            self.sidecar_template['RandomRate'].append(subheader.get('RANDOM_RATE', None))
            self.sidecar_template['SinglesRate'].append(subheader.get('SINGLES_RATE', None))

        # collect possible reconstruction method from subheader
        recon_method = get_recon_method(self.subheaders[0].get('ANNOTATION'))
        if recon_method:
            self.sidecar_template.update(**recon_method)

        # collect and convert start times for acquisition/time zero?
        scan_start_time = self.ecat_header.get('SCAN_START_TIME', None)

        if scan_start_time:
            scan_start_time = parse_this_date(scan_start_time)
            self.sidecar_template['AcquisitionTime'] = scan_start_time
            self.sidecar_template['ScanStart'] = scan_start_time

        # collect dose start time
        dose_start_time = self.ecat_header.get('DOSE_START_TIME', None)
        if dose_start_time:
            parsed_dose_time = parse_this_date(dose_start_time)
            self.sidecar_template['PharmaceuticalDoseTime'] = parsed_dose_time

        # if decay correction exists mark decay correction boolean as true
        if len(self.decay_factors) > 0:
            self.sidecar_template['ImageDecayCorrected'] = "true"

        # calculate scaling factor
        sca = self.data.max() / 32767

        self.sidecar_template['DoseCalibrationFactor'] = sca * self.ecat_header.get('ECAT_CALIBRATION_FACTOR')
        self.sidecar_template['Filename'] = os.path.basename(self.nifti_file)
        self.sidecar_template['ImageSize'] = [
            self.subheaders[0]['X_DIMENSION'],
            self.subheaders[0]['Y_DIMENSION'],
            self.subheaders[0]['Z_DIMENSION'],
            self.ecat_header['NUM_FRAMES']
        ]

        self.sidecar_template['PixelDimensions'] = [
            self.subheaders[0]['X_PIXEL_SIZE'] * 10,
            self.subheaders[0]['Y_PIXEL_SIZE'] * 10,
            self.subheaders[0]['Z_PIXEL_SIZE'] * 10
        ]

        # add tag for conversion software
        self.sidecar_template['ConversionSoftware'] = 'pypet2bids'
        self.sidecar_template['ConversionSoftwareVersion'] = pypet2bids.helper_functions.get_version()

        # include any additional values
        if kwargs:
            self.sidecar_template.update(**kwargs)

    def prune_sidecar(self):
        """
        Eliminate unpopulated fields in sidecar while leaving in mandatory fields even if they are unpopulated.

        :return: a list of removed fields from the sidecar file
        """
        short_fields = list(self.sidecar_template_short.keys())
        full_fields = list(self.sidecar_template)
        exclude_list = []
        for field, value in self.sidecar_template.items():
            if value:
                # check to make sure value isn't a list of null types
                # e.g. if value = [None, None, None] we don't want to include it.
                if type(value) is list:
                    none_count = value.count(None)
                    if len(value) == none_count:
                        pass
                    else:
                        exclude_list.append(field)
                else:
                    exclude_list.append(field)

        exclude_list = exclude_list + short_fields

        destroy_list = set(full_fields) - set(exclude_list)

        destroyed = []
        for to_be_destroyed in destroy_list:
            destroyed.append(self.sidecar_template.pop(to_be_destroyed))

        return destroyed

    def show_sidecar(self, output_path=None):
        """
        Write sidecar file to a json or display to stdout if no filepath is supplied
        :param output_path: path to output a json file
        :return: None
        """
        self.prune_sidecar()
        if output_path:
            with open(output_path, 'w') as outfile:
                json.dump(self.sidecar_template, outfile, indent=4)
        else:
            print(json.dumps(self.sidecar_template, indent=4))

    def json_out(self):
        """
        Dumps entire ecat header and header info into stdout formatted as json.

        :return: None
        """
        temp_json = json.dumps(self.ecat_info, indent=4)
        print(temp_json)
