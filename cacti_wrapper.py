CACTI_ACCURACY = 70  # in your metric, please set the accuracy you think CACTI's estimations are

#-------------------------------------------------------------------------------
# CACTI7 wrapper for generating energy estimations for plain SRAM scraptchpad
#-------------------------------------------------------------------------------
import subprocess, os, csv, glob, tempfile, math, shutil, json
from datetime import datetime

class CactiWrapper:
    """
    an estimation plug-in
    """
    # -------------------------------------------------------------------------------------
    # Interface functions, function name, input arguments, and output have to adhere
    # -------------------------------------------------------------------------------------
    def __init__(self, output_prefix = ''):
        self.estimator_name =  "Cacti"
        self.output_prefix = output_prefix
        # example primitive classes supported by this estimator
        self.supported_pc = ['SRAM', 'DRAM', 'cache', 'Disk']
        self.records = {} # enable data reuse

    def primitive_action_supported(self, interface):
        """
        :param interface:
        - contains four keys:
        1. class_name : string
        2. attributes: dictionary of name: value
        3. action_name: string
        4. arguments: dictionary of name: value

        :type interface: dict

        :return return the accuracy if supported, return 0 if not
        :rtype: int

        """
        class_name = interface['class_name']
        attributes = interface['attributes']
        action_name = interface['action_name']
        arguments = interface['arguments']

        if class_name in self.supported_pc:
            attributes_supported_function = class_name + '_attr_supported'
            if getattr(self, attributes_supported_function)(attributes):
                action_supported_function = class_name + '_action_supported'
                accuracy = getattr(self, action_supported_function)(action_name, arguments)
                if accuracy is not None:
                    return accuracy

        return 0  # if not supported, accuracy is 0

    def estimate_energy(self, interface):
        """
        :param interface:
        - contains four keys:
        1. class_name : string
        2. attributes: dictionary of name: value
        3. action_name: string
        4. arguments: dictionary of name: value

       :return the estimated energy
       :rtype float

        """
        class_name = interface['class_name']
        query_function_name = class_name + '_estimate_energy'
        energy = getattr(self, query_function_name)(interface)
        return energy

    def primitive_area_supported(self, interface):

        """
        :param interface:
        - contains two keys:
        1. class_name : string
        2. attributes: dictionary of name: value

        :type interface: dict

        :return return the accuracy if supported, return 0 if not
        :rtype: int

        """
        class_name = interface['class_name']
        attributes = interface['attributes']

        if class_name in self.supported_pc:  # CACTI supports SRAM area estimation
            attributes_supported_function = class_name + '_attr_supported'
            if getattr(self, attributes_supported_function)(attributes):
                return CACTI_ACCURACY
        return 0  # if not supported, accuracy is 0


    def estimate_area(self, interface):
        """
        :param interface:
        - contains two keys:
        1. class_name : string
        2. attributes: dictionary of name: value

        :type interface: dict

        :return the estimated area
        :rtype: float

        """
        class_name = interface['class_name']
        query_function_name = class_name + '_estimate_area'
        area = getattr(self, query_function_name)(interface)
        return area


    def search_for_cacti_exec(self):
        # search the current directory first, top-down walk
        this_dir, this_filename = os.path.split(__file__)
        for root, directories, file_names in os.walk(this_dir):
            if 'obj_dbg' not in root:
                for file_name in file_names:
                    if file_name == 'cacti':
                        cacti_exec_path = root + os.sep + file_name
                        cacti_exec_dir = os.path.dirname(cacti_exec_path)
                        return cacti_exec_dir

        # search the PATH variable: search the directories provided in the PATH variable. top-down walk
        PATH_lst = os.environ['PATH'].split(os.pathsep)
        for path in PATH_lst:
            for root, directories, file_names in os.walk(os.path.abspath(path)):
                for file_name in file_names:
                    if file_name == 'cacti':
                        cacti_exec_path = root + os.sep + file_name
                        cacti_exec_dir = os.path.dirname(cacti_exec_path)
                        return cacti_exec_dir
                    
    # ----------------- Disk related ---------------------------
    def Disk_attr_supported(self, attributes):
        if 'width' in attributes:
            return True
        return False
    
    def Disk_action_supported(self, action_name, arguments):
        supported_actions = ['read', 'write', 'idle']
        if action_name in supported_actions:
            return 60
        return None
    
    def Disk_estimate_energy(self, interface):
        action_name = interface['action_name']
        width = interface['attributes']['width']

        if action_name == 'idle':
            # Not counting idle storage energy, only transfers
            return 0
        
        # Assuming NVME
        # https://devicetests.com/how-many-watts-does-an-ssd-use
        # Assuming around 3000MB/s
        if action_name == 'read':
            watts = 5
            bandwidth = 3000 * (1 << 20)
            pj_per_byte = watts * (10**12) / bandwidth
            pj_per_bit = pj_per_byte / 8
            return pj_per_bit * width
        elif action_name == 'write':
            watts = 6.5
            bandwidth = 3000 * (1 << 20)
            pj_per_byte = watts * (10**12) / bandwidth
            pj_per_bit = pj_per_byte / 8
            return pj_per_bit * width
        
    def Disk_estimate_area(self, interface):
        return 0

    # ----------------- DRAM related ---------------------------

    def DRAM_attr_supported(self, attributes):
        supported_attributes = {'type': ['DDR', 'DDR2', 'DDR3', 'DDR4', 'DDR5', 'HBM2', 'LPDDR', 'LPDDR2', 'LPDDR3', 'LPDDR4', 'LPDDR5']}
        if 'type' in attributes and 'width' in attributes:
            if attributes['type'] in supported_attributes['type']:
                return True
        return False

    def DRAM_action_supported(self, action_name, arguments):
        supported_actions = ['read', 'write', 'idle']
        if action_name in supported_actions:
            return CACTI_ACCURACY
        else:
            return None

    def DRAM_estimate_energy(self, interface):
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['width'] * attributes['depth'] // 8
        if size_in_bytes == 0:
            # zero size DRAM will simply have zero energy and area
            return 0
        wordsize_in_bytes = attributes['width'] // 8
        if 'n_banks' in attributes:
            desired_n_banks = attributes['n_banks']
        else:
            desired_n_banks = None
        dram_type = attributes['type']
        desired_action_name = interface['action_name']
        desired_entry_key = (desired_action_name, tech_node, size_in_bytes, wordsize_in_bytes, desired_n_banks, dram_type)
        if desired_entry_key not in self.records:
            self.DRAM_populate_data(interface)
        energy = self.records[desired_entry_key]
        return energy

    def DRAM_area_supported(self, interface):
        return True

    def DRAM_estimate_area(self, interface):
        # DRAM area is zero
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['width'] * attributes['depth'] // 8
        if size_in_bytes == 0:
            # zero size SRAM will simply have zero energy and area
            return 0
        wordsize_in_bytes = attributes['width'] // 8
        if 'n_banks' in attributes:
            desired_n_banks = attributes['n_banks']
        else:
            desired_n_banks = None
        dram_type = attributes['type']
        desired_entry_key = ('area', tech_node, size_in_bytes, wordsize_in_bytes, desired_n_banks, dram_type)
        if desired_entry_key not in self.records:
            self.DRAM_populate_data(interface)
        area = self.records[desired_entry_key]
        return area
    
    def cacti_wrapper_for_DRAM(self, cacti_exec_dir, tech_node, size_in_bytes, wordsize_in_bytes, n_banks, dram_type, cfg_file_path):
        tech_node_um = float(int(tech_node)/1000)  # technology node described in um
        dram_size = size_in_bytes
        one_gb = 1 << 30
        burst_size = wordsize_in_bytes
        if int(wordsize_in_bytes) < 4:  # minimum line size in cacti is 32-bit/4-byte
            burst_size = 4

        # dram types: ['DDR3','HBM2','GDDR5','LPDDR','LPDDR4']
        cell_type = '"comm-dram"'
        if dram_type.startswith('LPDDR'):
            cell_type = '"lp-dram"'

        dirname = os.path.dirname(__file__)
        dram_file = os.path.join(dirname, 'dram_types.json')
        with open(dram_file) as f:
            dram_info = json.load(f)

        my_dram_info = dram_info[dram_type]
        burst_length = my_dram_info["burst_length"]
        io_width = my_dram_info["io_width"]
        sys_frequency = my_dram_info["sys_frequency"]
        prefetch_width = my_dram_info["prefetch_width"]
        page_size_bits = my_dram_info["page_size"]
        page_size = page_size_bits // 8
        num_dram = my_dram_info["devices_per_dimm"]

        # Divide DRAM into ~8, each with smaller io width, to build full memory rank
        dram_size = dram_size // num_dram

        if int(dram_size) / int(page_size) < 32768:
            print('WARN: CACTI Plug-in...  intended DRAM size is smaller than 32768 pages')
            print('intended DRAM size:', dram_size)
            dram_size = int(page_size) * 32768  # minimum dram size: 32678 rows
            print('corrected DRAM size:', dram_size)

        if n_banks is None:
            n_banks = my_dram_info['banks']
        
        cfg_file_name = os.path.split(cfg_file_path)[1]
        default_cfg_file_path = os.path.join(os.path.dirname(cfg_file_path), 'default_DRAM.cfg')
        populated_cfg_file_path = cacti_exec_dir + '/' + cfg_file_name
        shutil.copyfile(default_cfg_file_path, populated_cfg_file_path)
        print("copy ", default_cfg_file_path, " to ", populated_cfg_file_path)
        f = open(populated_cfg_file_path, 'a+')
        f.write('\n############## User-Specified Hardware Attributes ##############\n')
        if dram_size <= one_gb:
            f.write('-size (bytes) ' + str(dram_size) + '\n')
        else:
            f.write('-size (Gb) ' + str(dram_size >> 30) + '\n')
        f.write('-UCA bank count '+ str(n_banks) + '\n')
        f.write('-technology (u) ' + str(tech_node_um) + '\n')
        f.write('-Data array cell type - ' + cell_type + '\n')
        f.write('-burst depth ' + str(burst_length) + '\n')
        f.write('-IO width ' + str(io_width) + '\n')
        f.write('-system frequency (MHz) ' + str(sys_frequency) + '\n')
        f.write('-internal prefetch width ' + str(prefetch_width) + '\n')
        f.write('-output/input bus width ' + str(io_width) + '\n')
        f.write('-block size (bytes) ' + str(burst_size) + '\n')
        f.write('-page size (bits) ' + str(page_size_bits) + '\n')

        f.close()

        # create a temporary output file to redirect terminal output of cacti
        if os.path.isfile(cacti_exec_dir + 'tmp_output.txt'):
            os.remove(cacti_exec_dir + 'tmp_output.txt')
        temp_output =  tempfile.mkstemp()[0]
        # call cacti executable to evaluate energy consumption
        cacti_exec_path = cacti_exec_dir + '/cacti'
        exec_list = [cacti_exec_path, '-infile', cfg_file_name]
        subprocess.call(exec_list, stdout=temp_output)

        temp_dir = tempfile.gettempdir()
        accelergy_tmp_dir = os.path.join(temp_dir, 'accelergy')
        if os.path.exists(accelergy_tmp_dir):
            if len(os.listdir(accelergy_tmp_dir)) > 50: # clean up the dir if there are more than 50 files
                shutil.rmtree(accelergy_tmp_dir, ignore_errors=True)
                os.mkdir(accelergy_tmp_dir)
        else:
            os.mkdir(accelergy_tmp_dir)
        # shutil.copy(populated_cfg_file_path,
        #             os.path.join(temp_dir, 'accelergy/'+ cfg_file_name + '_' + datetime.now().strftime("%m_%d_%H_%M_%S")))
        print("CACTI plug-in removing temp file: ", populated_cfg_file_path)
        os.remove(populated_cfg_file_path)


    def DRAM_populate_data(self, interface):
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit

        size_in_bytes = attributes['width'] * attributes['depth'] // 8
        wordsize_in_bytes = attributes['width'] // 8
        dram_type = attributes['type']

        if 'n_banks' in attributes:
            desired_n_banks = attributes['n_banks']
            if not math.ceil(math.log2(n_banks)) == math.floor(math.log2(n_banks)):
                n_banks = 2**(math.ceil(math.log2(n_banks)))
                print('WARN: Cacti-plug-in... n_banks attribute is not a power of 2:', desired_n_banks)
                print('corrected "n_banks": ', n_banks)
        else:
            desired_n_banks = None
            n_banks = None

        dirname = os.path.dirname(__file__)
        dram_file = os.path.join(dirname, 'dram_types.json')
        with open(dram_file) as f:
            dram_info = json.load(f)

        my_dram_info = dram_info[dram_type]
        num_dram = my_dram_info["devices_per_dimm"]
        
        print('Info: CACTI plug-in... Querying CACTI for request:\n', interface)
        curr_dir = os.path.abspath(os.getcwd())
        cacti_exec_dir = self.search_for_cacti_exec()
        os.chdir(cacti_exec_dir)

        cfg_file_name = self.output_prefix + datetime.now().strftime("%m_%d_%H_%M_%S") + '_DRAM.cfg' if self.output_prefix is not '' \
                        else  datetime.now().strftime("%m_%d_%H_%M_%S") + '_DRAM.cfg'
        cfg_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg_file_name)
        self.cacti_wrapper_for_DRAM(cacti_exec_dir, tech_node, size_in_bytes, wordsize_in_bytes,
                                    n_banks, dram_type, cfg_file_path)
        
        for action_name in ['read', 'write', 'idle']:
            entry_key = (action_name, tech_node, size_in_bytes, wordsize_in_bytes, desired_n_banks, dram_type)
            if action_name == 'read':
                cacti_entry = ' Dynamic read energy (nJ)'  # nJ
            elif action_name == 'write':
                cacti_entry = ' Dynamic write energy (nJ)'  # nJ
            else:
                cacti_entry = ' Standby leakage per bank(mW)'  # mW
            csv_file_path = cacti_exec_dir + '/' + cfg_file_name + '.out'
            # query Cacti
            with open(csv_file_path) as csv_file:
                reader = csv.DictReader(csv_file)
                row = list(reader)[-1]
                if not action_name == 'idle':
                    energy = num_dram * float(row[cacti_entry]) * 10 ** 3  # original energy is in has nJ as the unit
                else:
                    standby_power_in_w = float(row[cacti_entry]) * 10 ** -3  # mW -> W
                    idle_energy_per_bank_in_j = standby_power_in_w * float(row[' Random cycle time (ns)']) * 10 ** -9
                    idle_energy_per_bank_in_pj = idle_energy_per_bank_in_j * 10 ** 12
                    energy = num_dram * idle_energy_per_bank_in_pj * float(row[' Number of banks'])
            # record energy entry
            self.records.update({entry_key: energy})

        # record area entry
        entry_key = ('area', tech_node, size_in_bytes, wordsize_in_bytes, desired_n_banks, dram_type)
        area = float(row[' Area (mm2)']) * 10**6 # area in micron squared
        self.records.update({entry_key: area})
        os.remove(csv_file_path)  # all information recorded, no need for saving the file
        os.chdir(curr_dir)
   
    # ----------------- SRAM related ---------------------------
    def SRAM_populate_data(self, interface):
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['width'] * attributes['depth'] // 8
        wordsize_in_bytes = attributes['width'] // 8
        n_rw_ports = attributes['n_rdwr_ports'] + attributes['n_rd_ports'] + attributes['n_wr_ports']
        desired_n_banks = attributes['n_banks']
        n_banks = desired_n_banks
        if not math.ceil(math.log2(n_banks)) == math.floor(math.log2(n_banks)):
            n_banks = 2**(math.ceil(math.log2(n_banks)))
        print('Info: CACTI plug-in... Querying CACTI for request:\n', interface)
        curr_dir = os.path.abspath(os.getcwd())
        cacti_exec_dir = self.search_for_cacti_exec()
        os.chdir(cacti_exec_dir)
        # check if the generated data already covers the case
        if not math.ceil(math.log2(desired_n_banks)) == math.floor(math.log2(desired_n_banks)):
            print('WARN: Cacti-plug-in... n_banks attribute is not a power of 2:', desired_n_banks)
            print('corrected "n_banks": ', n_banks)
        cfg_file_name = self.output_prefix + datetime.now().strftime("%m_%d_%H_%M_%S") + '_SRAM.cfg' if self.output_prefix is not '' \
                        else  datetime.now().strftime("%m_%d_%H_%M_%S") + '_SRAM.cfg'
        cfg_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg_file_name)
        self.cacti_wrapper_for_SRAM(cacti_exec_dir, tech_node, size_in_bytes, wordsize_in_bytes, n_rw_ports,
                                    n_banks, cfg_file_path)
        for action_name in ['read', 'write', 'idle']:
            entry_key = (action_name, tech_node, size_in_bytes, wordsize_in_bytes, n_rw_ports, desired_n_banks)
            if action_name == 'read':
                cacti_entry = ' Dynamic read energy (nJ)'  # nJ
            elif action_name == 'write':
                cacti_entry = ' Dynamic write energy (nJ)'  # nJ
            else:
                cacti_entry = ' Standby leakage per bank(mW)'  # mW
            csv_file_path = cacti_exec_dir + '/' + cfg_file_name + '.out'
            # query Cacti
            with open(csv_file_path) as csv_file:
                reader = csv.DictReader(csv_file)
                row = list(reader)[-1]
                if not action_name == 'idle':
                    energy = float(row[cacti_entry]) * 10 ** 3  # original energy is in has nJ as the unit
                else:
                    standby_power_in_w = float(row[cacti_entry]) * 10 ** -3  # mW -> W
                    idle_energy_per_bank_in_j = standby_power_in_w * float(row[' Random cycle time (ns)']) * 10 ** -9
                    idle_energy_per_bank_in_pj = idle_energy_per_bank_in_j * 10 ** 12
                    energy = idle_energy_per_bank_in_pj * n_banks
            # record energy entry
            self.records.update({entry_key: energy})

        # record area entry
        entry_key = ('area', tech_node, size_in_bytes, wordsize_in_bytes, n_rw_ports, desired_n_banks)
        area = float(row[' Area (mm2)']) * 10**6 # area in micron squared
        self.records.update({entry_key: area})
        os.remove(csv_file_path)  # all information recorded, no need for saving the file
        os.chdir(curr_dir)

    def SRAM_estimate_area(self, interface):
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['width'] * attributes['depth'] // 8
        if size_in_bytes == 0:
            # zero size SRAM will simply have zero energy and area
            return 0
        wordsize_in_bytes = attributes['width'] // 8
        n_rw_ports = attributes['n_rdwr_ports'] + attributes['n_rd_ports'] + attributes['n_wr_ports']
        desired_n_banks = attributes['n_banks']
        desired_entry_key = ('area', tech_node, size_in_bytes, wordsize_in_bytes, n_rw_ports, desired_n_banks)
        if desired_entry_key not in self.records:
            self.SRAM_populate_data(interface)
        area = self.records[desired_entry_key]
        return area

    def SRAM_estimate_energy(self, interface):
        # translate the attribute names into the ones that can be understood by Cacti
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['width'] * attributes['depth'] // 8
        if size_in_bytes == 0:
            # zero size SRAM will simply have zero energy and area
            return 0
        wordsize_in_bytes = attributes['width'] // 8
        n_rw_ports = attributes['n_rdwr_ports'] + attributes['n_rd_ports'] + attributes['n_wr_ports']
        desired_n_banks = attributes['n_banks']
        desired_action_name = interface['action_name']
        desired_entry_key = (desired_action_name, tech_node, size_in_bytes, wordsize_in_bytes, n_rw_ports, desired_n_banks)
        if desired_entry_key not in self.records:
            self.SRAM_populate_data(interface)
        if desired_action_name == 'idle':
            energy = self.records[desired_entry_key]
        else:
            if interface["arguments"] is not None:
                address_delta = interface['arguments']['address_delta']
                data_delta = interface['arguments']['data_delta']
            else:
                # allow SRAM classes without arguments, default to random accesses
                address_delta = 1
                data_delta = 1
            if address_delta == 0 and data_delta == 0:
                interpreted_entry_key = ('idle', tech_node, size_in_bytes, wordsize_in_bytes, n_rw_ports, desired_n_banks)
                energy = self.records[interpreted_entry_key]
            else:
                # rough estimate: address decoding takes 30%, memory_cell_access_energy takes 70%
                idle_energy = self.records[('idle', tech_node, size_in_bytes, wordsize_in_bytes,n_rw_ports, desired_n_banks)]
                address_decoding_energy = (self.records[desired_entry_key] - idle_energy) * 0.3 * address_delta/desired_n_banks
                memory_cell_access_energy = (self.records[desired_entry_key] - idle_energy) * 0.7 * data_delta
                energy = address_decoding_energy + memory_cell_access_energy + idle_energy
        return energy  # output energy is pJ

    def SRAM_attr_supported(self, attributes):
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['width'] * attributes['depth'] // 8
        if size_in_bytes == 0:
            # zero size SRAM will simply have zero energy and area
            return True
        else:
            if size_in_bytes < 64:
                return False  # Cacti only estimates energy for SRAM size larger than 64B (512b)
            if int(tech_node) < 22 or int(tech_node) > 180:
                return False  # Cacti only supports technology that is between 22nm to 180 nm
        return True

    def SRAM_action_supported(self, action_name, arguments):
        supported_action_names = ['read', 'write', 'idle']
        # Cacti ignores the arguments to the read and write actions
        if action_name in supported_action_names:
            return CACTI_ACCURACY # Cacti accuracy
        else:
            return None

    def cacti_wrapper_for_SRAM(self, cacti_exec_dir, tech_node, size_in_bytes, wordsize_in_bytes, n_rw_ports, n_banks, cfg_file_path):
        tech_node_um = float(int(tech_node)/1000)  # technology node described in um
        cache_size = size_in_bytes
        block_size = wordsize_in_bytes
        if int(wordsize_in_bytes) < 4:  # minimum line size in cacti is 32-bit/4-byte
            block_size = 4
        if int(cache_size) / int(block_size) < 64:
            print('WARN: CACTI Plug-in...  intended SRAM size is smaller than 64 words')
            print('intended SRAM size:', cache_size, 'block size:', block_size)
            cache_size = int(block_size) * 64  # minimum scratchpad size: 64 words
            print('corrected SRAM size:', cache_size)
        output_width = int(wordsize_in_bytes) * 8
        rw_ports = n_rw_ports  # assumes that all the ports in the plain scratchpad are read write ports instead of exclusive ports
        if int(rw_ports) == 0:
            rw_ports = 1  # you must have at least one port
        cfg_file_name = os.path.split(cfg_file_path)[1]
        default_cfg_file_path = os.path.join(os.path.dirname(cfg_file_path), 'default_SRAM.cfg')
        populated_cfg_file_path = cacti_exec_dir + '/' + cfg_file_name
        shutil.copyfile(default_cfg_file_path, populated_cfg_file_path)
        print("copy ", default_cfg_file_path, " to ", populated_cfg_file_path)
        f = open(populated_cfg_file_path, 'a+')
        f.write('\n############## User-Specified Hardware Attributes ##############\n')
        f.write('-size (bytes) ' + str(cache_size) + '\n')
        f.write('-read-write port  ' + str(rw_ports) + '\n')
        f.write('-block size (bytes) ' + str(block_size) + '\n')
        f.write('-technology (u) ' + str(tech_node_um) + '\n')
        f.write('-output/input bus width  ' + str(output_width) + '\n')
        f.write('-UCA bank '+ str(n_banks) + '\n')
        f.close()

        # create a temporary output file to redirect terminal output of cacti
        if os.path.isfile(cacti_exec_dir + 'tmp_output.txt'):
            os.remove(cacti_exec_dir + 'tmp_output.txt')
        temp_output =  tempfile.mkstemp()[0]
        # call cacti executable to evaluate energy consumption
        cacti_exec_path = cacti_exec_dir + '/cacti'
        exec_list = [cacti_exec_path, '-infile', cfg_file_name]
        subprocess.call(exec_list, stdout=temp_output)

        temp_dir = tempfile.gettempdir()
        accelergy_tmp_dir = os.path.join(temp_dir, 'accelergy')
        if os.path.exists(accelergy_tmp_dir):
            if len(os.listdir(accelergy_tmp_dir)) > 50: # clean up the dir if there are more than 50 files
                shutil.rmtree(accelergy_tmp_dir, ignore_errors=True)
                os.mkdir(accelergy_tmp_dir)
        else:
            os.mkdir(accelergy_tmp_dir)
        # shutil.copy(populated_cfg_file_path,
        #             os.path.join(temp_dir, 'accelergy/'+ cfg_file_name + '_' + datetime.now().strftime("%m_%d_%H_%M_%S")))
        print("CACTI plug-in removing temp file: ", populated_cfg_file_path)
        os.remove(populated_cfg_file_path)

    # ----------------- cache related ---------------------------
    def cache_populate_data(self, interface):
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['size']
        blocksize_in_bytes = attributes['block_size']
        n_rw_ports = attributes['n_rdwr_ports'] + attributes['n_rd_ports'] + attributes['n_wr_ports']
        desired_n_banks = attributes['n_banks']
        n_banks = desired_n_banks
        if not math.ceil(math.log2(n_banks)) == math.floor(math.log2(n_banks)):
            n_banks = 2**(math.ceil(math.log2(n_banks)))
        associativity = attributes['associativity']
        tag_size = attributes['tag_size']
        print('Info: CACTI plug-in... Querying CACTI for request:\n', interface)
        curr_dir = os.path.abspath(os.getcwd())
        cacti_exec_dir = self.search_for_cacti_exec()
        os.chdir(cacti_exec_dir)
        # check if the generated data already covers the case
        if not math.ceil(math.log2(desired_n_banks)) == math.floor(math.log2(desired_n_banks)):
            print('WARN: Cacti-plug-in... n_banks attribute is not a power of 2:', desired_n_banks)
            print('corrected "n_banks": ', n_banks)
        cfg_file_name = self.output_prefix + 'cache.cfg' if self.output_prefix is not '' else 'cache.cfg'
        cfg_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg_file_name)
        self.cacti_wrapper_for_cache(cacti_exec_dir, tech_node, size_in_bytes, blocksize_in_bytes, n_rw_ports,
                                    n_banks, associativity, tag_size, cfg_file_path)
        for action_name in ['read_access', 'write_access', 'idle']:
            entry_key = (action_name, tech_node, size_in_bytes, blocksize_in_bytes, n_rw_ports, desired_n_banks, associativity, tag_size)
            if action_name == 'read_access':
                cacti_entry = ' Dynamic read energy (nJ)'  # nJ
            elif action_name == 'write_access':
                cacti_entry = ' Dynamic write energy (nJ)'  # nJ
            else:
                cacti_entry = ' Standby leakage per bank(mW)'  # mW
            csv_file_path = cacti_exec_dir + '/' + cfg_file_name + '.out'
            # query Cacti
            with open(csv_file_path) as csv_file:
                reader = csv.DictReader(csv_file)
                row = list(reader)[-1]
                if not action_name == 'idle':
                    energy = float(row[cacti_entry]) * 10 ** 3  # original energy is in has nJ as the unit
                else:
                    standby_power_in_w = float(row[cacti_entry]) * 10 ** -3  # mW -> W
                    idle_energy_per_bank_in_j = standby_power_in_w * float(row[' Random cycle time (ns)']) * 10 ** -9
                    idle_energy_per_bank_in_pj = idle_energy_per_bank_in_j * 10 ** 12
                    energy = idle_energy_per_bank_in_pj * n_banks
            # record energy entry
            self.records.update({entry_key: energy})

        # record area entry
        entry_key = ('area', tech_node, size_in_bytes, blocksize_in_bytes, n_rw_ports, desired_n_banks, associativity, tag_size)
        area = float(row[' Area (mm2)']) * 10**6 # area in micron squared
        self.records.update({entry_key: area})
        os.remove(csv_file_path)  # all information recorded, no need for saving the file
        os.chdir(curr_dir)

    def cache_estimate_area(self, interface):
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['size']
        blocksize_in_bytes = attributes['block_size']
        n_rw_ports = attributes['n_rdwr_ports'] + attributes['n_rd_ports'] + attributes['n_wr_ports']
        desired_n_banks = attributes['n_banks']
        associativity = attributes['associativity']
        tag_size = attributes['tag_size']
        desired_entry_key = ('area', tech_node, size_in_bytes, blocksize_in_bytes, n_rw_ports, desired_n_banks, associativity, tag_size)
        if desired_entry_key not in self.records:
            self.cache_populate_data(interface)
        area = self.records[desired_entry_key]
        return area

    def cache_estimate_energy(self, interface):
        # translate the attribute names into the ones that can be understood by Cacti
        attributes = interface['attributes']
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['size']
        blocksize_in_bytes = attributes['block_size']
        n_rw_ports = attributes['n_rdwr_ports'] + attributes['n_rd_ports'] + attributes['n_wr_ports']
        desired_n_banks = attributes['n_banks']
        associativity = attributes['associativity']
        tag_size = attributes['tag_size']
        desired_action_name = interface['action_name']
        desired_entry_key = (desired_action_name, tech_node, size_in_bytes, blocksize_in_bytes, n_rw_ports, desired_n_banks, associativity, tag_size)
        if desired_entry_key not in self.records:
            self.cache_populate_data(interface)
        if desired_action_name == 'idle':
            energy = self.records[desired_entry_key]
        else:
            # address_delta = interface['arguments']['address_delta']
            # data_delta = interface['arguments']['data_delta']
            # using these defaults for now
            address_delta = 1
            data_delta = 1
            # if address_delta == 0 and data_delta == 0:
            #     interpreted_entry_key = ('idle', tech_node, size_in_bytes, wordsize_in_bytes, n_rw_ports, desired_n_banks)
            #     energy = self.records[interpreted_entry_key]
            # else:
            # rough estimate: address decoding takes 30%, memory_cell_access_energy takes 70%
            idle_energy = self.records[('idle', tech_node, size_in_bytes, blocksize_in_bytes,n_rw_ports, desired_n_banks, associativity, tag_size)]
            address_decoding_energy = (self.records[desired_entry_key] - idle_energy) * 0.3 * address_delta/desired_n_banks
            memory_cell_access_energy = (self.records[desired_entry_key] - idle_energy) * 0.7 * data_delta
            energy = address_decoding_energy + memory_cell_access_energy + idle_energy
        return energy  # output energy is pJ

    def cache_attr_supported(self, attributes):
        tech_node = attributes['technology']
        if isinstance(tech_node, str) and 'nm' in tech_node:
            tech_node = tech_node[:-2]  # remove the unit
        size_in_bytes = attributes['size']
        if size_in_bytes < 64:
            return False  # Cacti only estimates energy for SRAM size larger than 64B (512b)
        if int(tech_node) < 22 or int(tech_node) > 180:
            return False  # Cacti only supports technology that is between 22nm to 180 nm
        return True

    def cache_action_supported(self, action_name, arguments):
        supported_action_names = ['read_access', 'write_access', 'idle']
        # Cacti ignores the arguments to the read and write actions
        if action_name in supported_action_names:
            return CACTI_ACCURACY # Cacti accuracy
        else:
            return None

    def cacti_wrapper_for_cache(self, cacti_exec_dir, tech_node, size_in_bytes, blocksize_in_bytes, n_rw_ports, n_banks, associativity, tag_size, cfg_file_path):
        tech_node_um = float(int(tech_node)/1000)  # technology node described in um
        cache_size = size_in_bytes
        block_size = blocksize_in_bytes
        if int(blocksize_in_bytes) < 4:  # minimum line size in cacti is 32-bit/4-byte
            block_size = 4
        if int(cache_size) / int(block_size) < 64:
            print('WARN: CACTI Plug-in...  intended cache size is smaller than 64 words')
            print('intended cache size:', cache_size, 'block size:', block_size)
            cache_size = int(block_size) * 64  # minimum scratchpad size: 64 words
            print('corrected cache size:', cache_size)
        output_width = int(blocksize_in_bytes) * 8 # TODO fix this later
        rw_ports = n_rw_ports  # assumes that all the ports in the plain scratchpad are read write ports instead of exclusive ports
        if int(rw_ports) == 0:
            rw_ports = 1  # you must have at least one port
        cfg_file_name = os.path.split(cfg_file_path)[1]
        default_cfg_file_path = os.path.join(os.path.dirname(cfg_file_path), 'default_SRAM.cfg')
        populated_cfg_file_path = cacti_exec_dir + '/' + cfg_file_name
        print("cacti_exec_dir: " + cacti_exec_dir)
        print("populated_cfg_file_path: " + populated_cfg_file_path)
        shutil.copyfile(default_cfg_file_path, cacti_exec_dir + '/' + cfg_file_name)
        f = open(populated_cfg_file_path, 'a+')
        f.write('\n############## User-Specified Hardware Attributes ##############\n')
        f.write('-size (bytes) ' + str(cache_size) + '\n')
        f.write('-associativity ' + str(associativity) + '\n')
        f.write('-read-write port  ' + str(rw_ports) + '\n')
        f.write('-tag_size (b)  ' + '\"default\"' + '\n')
        f.write('-block size (bytes) ' + str(block_size) + '\n')
        f.write('-technology (u) ' + str(tech_node_um) + '\n')
        f.write('-output/input bus width  ' + str(output_width) + '\n')
        f.write('-UCA bank count '+ str(n_banks) + '\n')
        f.close()

        # create a temporary output file to redirect terminal output of cacti
        if os.path.isfile(cacti_exec_dir + 'tmp_output.txt'):
            os.remove(cacti_exec_dir + 'tmp_output.txt')
        temp_output =  tempfile.mkstemp()[0]
        # call cacti executable to evaluate energy consumption
        cacti_exec_path = cacti_exec_dir + '/cacti'
        exec_list = [cacti_exec_path, '-infile', cfg_file_name]
        subprocess.call(exec_list, stdout=temp_output)

        temp_dir = tempfile.gettempdir()
        accelergy_tmp_dir = os.path.join(temp_dir, 'accelergy')
        if os.path.exists(accelergy_tmp_dir):
            if len(os.listdir(accelergy_tmp_dir)) > 50: # clean up the dir if there are more than 50 files
                shutil.rmtree(accelergy_tmp_dir, ignore_errors=True)
                os.mkdir(accelergy_tmp_dir)
        else:
            os.mkdir(accelergy_tmp_dir)
        shutil.copy(populated_cfg_file_path,
                    os.path.join(temp_dir, 'accelergy/'+ cfg_file_name + '_' + datetime.now().strftime("%m_%d_%H_%M_%S")))
        os.remove(populated_cfg_file_path)
