import os
import re
import numpy as np
import pickle
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd
from tabulate import tabulate

from dreem import settings
from dreem.mutation_histogram import MutationHistogram
from dreem.logger import get_logger
from dreem.sam import AlignedRead, SingleSamIterator, PairedSamIterator
from dreem.util import parse_phred_qscore_file, fasta_to_dict

log = get_logger("BIT_VECTOR")


@dataclass(frozen=True, order=True)
class BitVector:
    reads: List[AlignedRead]
    data: Dict


class BitVectorFileWriter(object):
    def __init__(self, path, name, sequence, data_type, start, end):
        self.start = start
        self.end = end
        self.sequence = sequence
        self.f = open(path + name + "_bitvectors.txt", "w")
        self.f.write("@ref\t{}\t{}\t{}\n".format(name, sequence, data_type))
        self.f.write(
            "@coordinates:\t{},{}:{}\n".format(0, len(sequence), len(sequence))
        )
        self.f.write("Query_name\tBit_vector\tN_Mutations\n")

    def write_bit_vector(self, q_name, bit_vector):
        n_mutations = 0
        bit_string = ""
        for pos in range(self.start, self.end + 1):
            if pos not in bit_vector:
                bit_string += "."
            else:
                read_bit = bit_vector[pos]
                if read_bit.isalpha():
                    n_mutations += 1
                bit_string += read_bit
        self.f.write("{}\t{}\t{}\n".format(q_name, bit_string, n_mutations))


class BitVectorFileReader(object):
    def __init__(self):
        pass


class BitVectorIterator(object):
    def __init__(
        self, sam_path, ref_seqs, paired, qscore_cutoff=25, num_of_surbases=10
    ):
        if paired:
            self.__sam_iterator = PairedSamIterator(sam_path, ref_seqs)
        else:
            self.__sam_iterator = SingleSamIterator(sam_path, ref_seqs)
        self.count = 0
        self.rejected = 0
        self.__ref_seqs = ref_seqs
        self.__paired = paired
        self.__cigar_pattern = re.compile(r"(\d+)([A-Z]{1})")
        self.__phred_qscores = parse_phred_qscore_file(
            settings.get_py_path() + "/resources/phred_ascii.txt"
        )
        # params
        self.__bases = ["A", "C", "G", "T"]
        self.__qscore_cutoff = qscore_cutoff
        self.__num_of_surbases = num_of_surbases
        self.__miss_info = "*"
        self.__ambig_info = "?"
        self.__nomut_bit = "0"
        self.__del_bit = "1"

    def __iter__(self):
        return self

    def __next__(self):
        self.count += 1
        reads = next(self.__sam_iterator)
        for read in reads:
            if read not in self.__ref_seqs:
                raise ValueError(
                    f"read {read.qname} aligned to {read.rname} which is not in "
                    f"the reference fasta"
                )
        if self.__paired:
            data = self.__get_bit_vector_paired(reads[0], reads[1])
        else:
            data = self.__get_bit_vector_single(reads[0])
        return BitVector(reads, data)

    def __get_bit_vector_single(self, read):
        ref_seq = self.__ref_seqs[read.rname]
        bit_vector = self.__convert_read_to_bit_vector(read, ref_seq)
        return bit_vector

    def __convert_read_to_bit_vector(self, read: AlignedRead, ref_seq: str):
        bitvector = {}
        read_seq = read.seq
        q_scores = read.qual
        i = read.pos  # Pos in the ref sequence
        j = 0  # Pos in the read sequence
        cigar_ops = self._parse_cigar(read.cigar)
        op_index = 0
        while op_index < len(cigar_ops):
            op = cigar_ops[op_index]
            desc, length = op[1], int(op[0])
            if desc == "M":  # Match or mismatch
                for k in range(length):
                    if self.__phred_qscores[q_scores[j]] > self.__qscore_cutoff:
                        if read_seq[j] != ref_seq[i - 1]:
                            bitvector[i] = read_seq[j]
                        else:
                            bitvector[i] = self.__nomut_bit
                    else:
                        bitvector[i] = self.__ambig_info
                    i += 1
                    j += 1
            elif desc == "D":  # Deletion
                for k in range(length - 1):
                    bitvector[i] = self.__ambig_info
                    i += 1
                is_ambig = self.__calc_ambig_reads(ref_seq, i, length)
                if is_ambig:
                    bitvector[i] = self.__ambig_info
                else:
                    bitvector[i] = self.__del_bit
                i += 1
            elif desc == "I":  # Insertion
                j += length  # Update read index
            elif desc == "S":  # soft clipping
                j += length  # Update read index
                if op_index == len(cigar_ops) - 1:  # Soft clipped at the end
                    for k in range(length):
                        bitvector[i] = self.__miss_info
                        i += 1
            else:
                log.warn("unknown cigar op encounters: {}".format(desc))
                return {}
            op_index += 1
        return bitvector

    def __get_bit_vector_paired(self, read_1, read_2):
        ref_seq = self.__ref_seqs[read_1.rname]
        bit_vector_1 = self.__convert_read_to_bit_vector(read_1, ref_seq)
        bit_vector_2 = self.__convert_read_to_bit_vector(read_2, ref_seq)
        bit_vector = self.__merge_paired_bit_vectors(bit_vector_1, bit_vector_2)
        return bit_vector

    def _parse_cigar(self, cigar_string):
        return re.findall(self.__cigar_pattern, cigar_string)

    def __calc_ambig_reads(self, ref_seq, i, length):
        orig_del_start = i - length + 1
        orig_sur_start = orig_del_start - self.__num_of_surbases
        orig_sur_end = i + self.__num_of_surbases
        orig_sur_seq = (
            ref_seq[orig_sur_start - 1 : orig_del_start - 1]
            + ref_seq[i:orig_sur_end]
        )
        for new_del_end in range(
            i - length, i + length + 1
        ):  # Alt del end points
            if new_del_end == i:  # Orig end point
                continue
            new_del_start = new_del_end - length + 1
            sur_seq = (
                ref_seq[orig_sur_start - 1 : new_del_start - 1]
                + ref_seq[new_del_end:orig_sur_end]
            )
            if sur_seq == orig_sur_seq:
                return True
        return False

    def __merge_paired_bit_vectors(self, bit_vector_1, bit_vector_2):
        bit_vector = dict(bit_vector_1)
        for pos, bit in bit_vector_2.items():
            if pos not in bit_vector:  # unique to bit_vector_2
                bit_vector[pos] = bit
            elif bit != bit_vector[pos]:  # keys in both and bits not the same
                bits = set([bit_vector_1[pos], bit])
                if (
                    self.__nomut_bit in bits
                ):  # one of the bits is not mutated take that
                    bit_vector[pos] = self.__nomut_bit
                # one of the bits is ambig take the other
                elif self.__ambig_info in bits:
                    other_bit = list(bits - set(self.__ambig_info))[0]
                    bit_vector[pos] = other_bit
                # one of the bits is missing take the other
                elif self.__miss_info in bits:
                    other_bit = list(bits - set(self.__miss_info))[0]
                    bit_vector[pos] = other_bit
                # both bits are mutations and different set to "?"
                elif bit_vector_1[pos] in self.__bases and bit in self.__bases:
                    bit_vector[pos] = self.__ambig_info
                # mutation on one side and insertion on the other side set to "?"
                elif (
                    bit_vector_1[pos] == self.__del_bit
                    and bit in self.__bases
                    or bit_vector_1[pos] in self.__bases
                    and bit == self.__del_bit
                ):
                    bit_vector[pos] = self.__ambig_info
                else:
                    log.warn(
                        "unable to merge bit_vectors with bits: {} {}".format(
                            bit_vector_1[pos], bit
                        )
                    )
        return bit_vector


class BitVectorGenerator(object):
    def __init__(self):
        self.__bases = ["A", "C", "G", "T"]

    def run(self, sam_path, fasta, paired, csv_file, params):
        log.info("starting bitvector generation")
        self.__ref_seqs = fasta_to_dict(fasta)
        self.__bit_vec_iterator = BitVectorIterator(
            sam_path, self.__ref_seqs, paired
        )
        self.__map_score_cutoff = params["bitvector"]["map_score_cutoff"]
        self.__csv_file = csv_file
        self.__out_dir = params["dirs"]["output"] + "/BitVector_Files/"
        self.__summary_only = params["bit_vector"]["summary_output_only"]
        self.__params = params
        # setup parameters about generating bit vectors
        # self.__run_picard_sam_convert()
        self.__generate_all_bit_vectors()
        self.__generate_plots()
        #self.__write_summary_csv()

    def __write_summary_csv(self):
        f = open("output/BitVector_Files/summary.csv", "w")
        s = "name,reads,aligned,no_mut,1_mut,2_mut,3_mut,3plus_mut,sn"
        f.write(s + "\n")
        headers = s.split(",")
        table = []
        for mh in self._mut_histos.values():
            try:
                data = [
                    mh.name,
                    mh.num_reads,
                    round(mh.num_aligned / mh.num_reads * 100, 2),
                ]
            except:
                data = [mh.name, mh.num_reads, 0]
            data += mh.get_percent_mutations()
            data.append(mh.get_signal_to_noise())
            table.append(data)
            f.write(",".join([str(x) for x in data]) + "\n")
        log.info(
            "MUTATION SUMMARY:\n" + tabulate(table, headers, tablefmt="github")
        )
        f.close()

    def __generate_plots(self):
        """for mh in self._mut_histos.values():
            if not p.bit_vector.summary_output_only:
                plot_population_avg(mh, p)
            if p.restore_org_behavior:
                plot_population_avg_old(mh, p)
                plot_read_coverage(mh, p)
                plot_modified_bases(mh, p)
                plot_mutation_histogram(mh, p)
                generate_quality_control_file(mh, p)"""
        pass

    def __generate_all_bit_vectors(self):
        self._mut_histos = {}
        """if (
            os.path.isfile(bit_vector_pickle_file)
            and not self._p.bit_vector.overwrite
        ):
            log.info(
                "SKIPPING bit vector generation, it has run already! specify -overwrite "
                + "to rerun"
            )
            with open(bit_vector_pickle_file, "rb") as handle:
                self._mut_histos = pickle.load(handle)
            return"""

        self._bit_vector_writers = {}
        for ref_name, seq in self.__ref_seqs.items():
            self._mut_histos[ref_name] = MutationHistogram(
                ref_name, seq, "DMS", 1, len(seq)
            )
            if not self.__summary_only:
                self._bit_vector_writers[ref_name] = BitVectorFileWriter(
                    self.__out_dir, ref_name, seq, "DMS", 1, len(seq)
                )
        for bit_vector in self.__bit_vec_iterator:
            self.__record_bit_vector(bit_vector)
        if self.__csv_file is not None:
            df = pd.read_csv(self.__csv_file)
            for i, row in df.iterrows():
                if row["name"] in self._mut_histos:
                    self._mut_histos[row["name"]].structure = row["structure"]
        bit_vector_pickle_file = "output/BitVector_Files/mutation_histos.p"
        f = open(self.__out_dir + "mutation_histos.p", "wb")
        pickle.dump(self._mut_histos, f)

    def __record_bit_vector(self, bit_vector):
        read = bit_vector.reads[0]
        ref_seq = self.__ref_seqs[read.rname]
        mh = self._mut_histos[read.rname]
        per = len(bit_vector.data) / len(ref_seq)
        for read in bit_vector.reads:
            per = len(read.seq) / len(ref_seq)
            if per < self.__params["bit_vector"]["percent_length_cutoff"]:
                mh.record_skip("short_read")
                return
            if read.mapq < self.__map_score_cutoff:
                mh.record_skip("low_mapq")
                return
        muts = 0
        for pos in range(mh.start, mh.end + 1):
            if pos not in bit_vector.data:
                continue
            read_bit = bit_vector.data[pos]
            if read_bit in self.__bases:
                muts += 1
        if muts > self.__params["bit_vector"]["mutation_count_cutoff"]:
            mh.record_skip("too_many_muts")
            return
        if not self.__params["bit_vector"]["summary_output_only"]:
            self._bit_vector_writers[read.rname].write_bit_vector(
                read.qname, bit_vector
            )
        mh.record_bit_vector(bit_vector, self.__params)

    def __run_picard_sam_convert(self):
        # TODO fix path
        if (
            os.path.isfile(self.__out_dir + "/converted.sam")
            and not self.__params["bit_vector"]["overwrite"]
        ):
            log.info(
                "SKIPPING picard SAM convert, it has been run already! specify "
                + "-overwrite to rerun"
            )
            return
