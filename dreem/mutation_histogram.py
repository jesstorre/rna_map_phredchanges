"""
tracking mutations
"""
from typing import Dict, List
import numpy as np
import pandas as pd
import json

import plotly
import plotly.graph_objs as go
from plotly.subplots import make_subplots


class MutationHistogram(object):
    def __init__(self, name, sequence, data_type, start=None, end=None):
        self.__bases = ["A", "C", "G", "T"]
        self.name = name
        self.sequence = sequence
        self.structure = None
        self.data_type = data_type
        self.num_reads = 0
        self.num_aligned = 0
        self.skips = {"low_mapq": 0, "short_read": 0, "too_many_muts": 0}
        self.num_of_mutations = [0] * (len(sequence) + 1)
        self.mut_bases = np.zeros(len(sequence) + 1)
        self.info_bases = np.zeros(len(sequence) + 1)
        self.del_bases = np.zeros(len(sequence) + 1)
        self.ins_bases = np.zeros(len(sequence) + 1)
        self.cov_bases = np.zeros(len(sequence) + 1)
        self.mod_bases = {
            "A": np.zeros(len(sequence) + 1),
            "C": np.zeros(len(sequence) + 1),
            "G": np.zeros(len(sequence) + 1),
            "T": np.zeros(len(sequence) + 1),
        }
        self.start = start
        self.end = end
        if self.start is None:
            self.start = 1
        if self.end is None:
            self.end = len(self.sequence)

    @classmethod
    def from_dict(cls, d):
        mh = cls(d["name"], d["sequence"], d["data_type"])
        mh.structure = d["structure"]
        mh.start = d["start"]
        mh.end = d["end"]
        mh.num_reads = d["num_reads"]
        mh.num_aligned = d["num_aligned"]
        mh.skips = d["skips"]
        mh.num_of_mutations = d["num_of_mutations"]
        mh.mut_bases = np.array(d["mut_bases"])
        mh.info_bases = np.array(d["info_bases"])
        mh.del_bases = np.array(d["del_bases"])
        mh.ins_bases = np.array(d["ins_bases"])
        mh.cov_bases = np.array(d["cov_bases"])
        mh.mod_bases["A"] = np.array(d["mod_bases"]["A"])
        mh.mod_bases["C"] = np.array(d["mod_bases"]["C"])
        mh.mod_bases["G"] = np.array(d["mod_bases"]["G"])
        mh.mod_bases["T"] = np.array(d["mod_bases"]["T"])
        return mh

    def get_dict(self):
        return {
            "name": self.name,
            "sequence": self.sequence,
            "structure": self.structure,
            "data_type": self.data_type,
            "start": self.start,
            "end": self.end,
            "num_reads": self.num_reads,
            "num_aligned": self.num_aligned,
            "skips": self.skips,
            "num_of_mutations": self.num_of_mutations,
            "mut_bases": self.mut_bases.tolist(),
            "info_bases": self.info_bases.tolist(),
            "del_bases": self.del_bases.tolist(),
            "ins_bases": self.ins_bases.tolist(),
            "cov_bases": self.cov_bases.tolist(),
            "mod_bases": {
                "A": self.mod_bases["A"].tolist(),
                "C": self.mod_bases["C"].tolist(),
                "G": self.mod_bases["G"].tolist(),
                "T": self.mod_bases["T"].tolist(),
            },
        }

    def merge(self, other) -> None:
        """
        Merges values from another histogram and ensures the merge is done
        correctly
        """
        if self.name != other.name:
            raise ValueError(
                "MutationalHistogram names do not match cannot merge"
            )
        if self.sequence != other.sequence:
            raise ValueError(
                "MutationalHistogram sequences do not match cannot merge"
            )
        if self.data_type != other.data_type:
            raise ValueError(
                "MutationalHistogram data_types do not match cannot merge"
            )
        if self.start != other.start:
            raise ValueError(
                "MutationalHistogram starts do not match cannot merge"
            )
        if self.end != other.end:
            raise ValueError(
                "MutationalHistogram ends do not match cannot merge"
            )
        if self.structure != other.structure:
            raise ValueError(
                "MutationalHistogram structures do not match cannot merge"
            )
        self.num_reads += other.num_reads
        self.num_aligned += other.num_aligned
        for key in self.skips.keys():
            self.skips[key] += other.skips[key]
        for ii in range(len(other.num_of_mutations)):
            self.num_of_mutations[ii] += other.num_of_mutations[ii]
        self.mut_bases += other.mut_bases
        self.ins_bases += other.ins_bases
        self.cov_bases += other.cov_bases
        self.info_bases += other.info_bases
        for key in self.mod_bases.keys():
            self.mod_bases[key] += other.mod_bases[key]

    def record_bit_vector(self, bit_vector, p):
        self.num_reads += 1
        self.num_aligned += 1
        total_muts = 0
        for pos in self.get_nuc_coords():
            if pos not in bit_vector:
                continue
            read_bit = bit_vector[pos]
            if read_bit != p.bit_vector.ambig_info:
                self.cov_bases[pos] += 1
            if read_bit in self.__bases:
                total_muts += 1
                self.mod_bases[read_bit][pos] += 1
                self.mut_bases[pos] += 1
            elif read_bit == p.bit_vector.del_bit:
                self.del_bases[pos] += 1
            self.info_bases[pos] += 1
        self.num_of_mutations[total_muts] += 1

    def record_skip(self, t):
        self.num_reads += 1
        self.skips[t] += 1

    # getters ################################################################
    def get_read_coverage(self) -> np.ndarray:
        """
        Returns normalized read coverage
        """
        read_cov = []
        for pos in self.get_nuc_coords():
            try:
                cov_frac = self.cov_bases[pos] / self.num_reads
            except ZeroDivisionError:
                cov_frac = 0.0
            read_cov.append(cov_frac)
        return read_cov

    def get_nuc_coords(self) -> List[int]:
        """
        Returns the nucleotide coordinates of the histogram
        """
        return list(range(self.start, self.end + 1))

    def get_pop_avg(self, inc_del=False) -> List[float]:
        """
        Returns the population average of the histogram
        :param inc_del: if True, include deletions in the average
        """
        pop_avg = []
        for pos in self.get_nuc_coords():
            try:
                if inc_del:
                    mut_frac = (
                        self.del_bases[pos] + self.mut_bases[pos]
                    ) / self.info_bases[pos]
                else:
                    mut_frac = self.mut_bases[pos] / self.info_bases[pos]
            except:
                mut_frac = 0.0
            pop_avg.append(round(mut_frac, 5))
        return pop_avg

    def get_pop_avg_dataframe(self) -> pd.DataFrame:
        """
        Returns a dataframe of the population average
        """
        pop_avg = self.get_pop_avg(inc_del=False)
        pop_avg_del = self.get_pop_avg(inc_del=True)
        df = pd.DataFrame(
            {
                "position": self.get_nuc_coords(),
                "mismatches": pop_avg,
                "mismatch_del": pop_avg_del,
                "nuc": list(self.sequence),
            }
        )
        if self.structure is not None:
            df["structure"] = list(self.structure)
        return df

    def get_percent_mutations(self):
        data = np.array(
            self.num_of_mutations[0:4] + [sum(self.num_of_mutations[5:])]
        )
        data = [round(x, 2) for x in list((data / self.num_aligned) * 100)]
        return data

    def get_signal_to_noise(self):
        seq = self.sequence
        AC = 0
        GU = 0
        AC_count = seq.count("A") + seq.count("C")
        GU_count = seq.count("G") + seq.count("U") + seq.count("T")
        for pos in self.get_nuc_coords():
            if seq[pos - 1] == "A" or seq[pos - 1] == "C":
                AC += self.mut_bases[pos]
            else:
                GU += self.mut_bases[pos]
        AC /= float(AC_count)
        GU /= float(GU_count)
        return round(float(AC / GU), 2)


def get_mut_histos_from_json_file(fname: str) -> Dict[str, MutationHistogram]:
    """
    Returns a list of mutation histograms from a json file
    :param fname: the name of the json file
    """
    with open(fname, "r") as f:
        data = json.load(f)
    return {k: MutationHistogram.from_dict(v) for k, v in data.items()}


def get_dataframe(
    mut_histos: Dict[str, MutationHistogram], data_cols
) -> pd.DataFrame:
    """
    Returns a dataframe of the mutation histograms
    :param mut_histos: a dictionary of mutation histograms
    """
    data = []
    for _, mut_histo in mut_histos.items():
        data_row = []
        for dc in data_cols:
            if dc == "name":
                data_row.append(mut_histo.name)
            elif dc == "sequence":
                data_row.append(mut_histo.sequence)
            elif dc == "structure":
                data_row.append(mut_histo.structure)
            elif dc == "num_reads" or dc == "reads":
                data_row.append(mut_histo.num_reads)
            elif dc == "num_aligned" or dc == "aligned":
                data_row.append(mut_histo.num_aligned)
            elif dc == "num_of_mutations":
                data_row.append(mut_histo.num_of_mutations)
            elif dc == "no_mut":
                data_row.append(mut_histo.num_of_mutations[0])
            elif dc == "1_mut":
                data_row.append(mut_histo.num_of_mutations[1])
            elif dc == "2_mut":
                data_row.append(mut_histo.num_of_mutations[2])
            elif dc == "3_mut":
                data_row.append(mut_histo.num_of_mutations[3])
            elif dc == "3plus_mut":
                data_row.append(mut_histo.num_of_mutations[4])
            elif dc == "percent_mutations":
                data_row.append(mut_histo.get_percent_mutations())
            elif dc == "signal_to_noise":
                data_row.append(mut_histo.get_signal_to_noise())
            elif dc == "read_coverage":
                data_row.append(mut_histo.get_read_coverage())
            elif dc == "pop_avg":
                data_row.append(mut_histo.get_pop_avg())
            elif dc == "pop_avg_del":
                data_row.append(mut_histo.get_pop_avg(inc_del=True))
            elif dc == "skips":
                data_row.append(mut_histo.skips)
            elif dc == "mod_bases":
                data_row.append(mut_histo.mod_bases)
            elif dc == "mut_bases":
                data_row.append(mut_histo.mut_bases)
            elif dc == "del_bases":
                data_row.append(mut_histo.del_bases)
            elif dc == "cov_bases":
                data_row.append(mut_histo.cov_bases)
            elif dc == "info_bases":
                data_row.append(mut_histo.info_bases)
            else:
                raise ValueError("Invalid data column: {}".format(dc))
        data.append(data_row)
    return pd.DataFrame(data, columns=data_cols)


# plotting functions ###########################################################


def colors_for_sequence(seq: str) -> List[str]:
    """
    Returns a list of colors to plot a sequence with a barplot
    """
    colors = []
    for e in seq:
        if e == "A":
            colors.append("red")
        elif e == "C":
            colors.append("blue")
        elif e == "G":
            colors.append("orange")
        else:
            colors.append("green")
    return colors


# plotly functions ############################################################


def plot_read_coverage(nuc_pos, read_coverage, fname: str) -> None:
    """
    Plots the read coverage of the input sequence
    :param nuc_pos: a list of nucleotide positions generated by mh.get_nuc_coords()
    :param read_coverage: the coverage by nucleotide of number of reads
     mh.get_read_coverage()
    :param fname: the name of the file to save the plot to
    """
    cov_trace = go.Bar(x=nuc_pos, y=read_coverage)
    cov_layout = go.Layout(
        title="Read coverage: "
        + ", Number of bit vectors: "
        + str(max(read_coverage)),
        xaxis=dict(title="Position"),
        yaxis=dict(title="Coverage fraction"),
    )
    cov_fig = go.Figure(data=[cov_trace], layout=cov_layout)
    plotly.offline.plot(cov_fig, filename=fname, auto_open=False)


def plot_modified_bases(nuc_pos, mod_bases, fname) -> None:
    """
    Plots the modified bases of the input sequence
    :param nuc_pos: a list of nucleotide positions generated by mh.get_nuc_coords()
    :param mod_bases: the number of modified bases to each nucleotide
    """
    modbases_data = []
    cmap = {"A": "red", "T": "green", "G": "orange", "C": "blue"}  # Color map
    for base in cmap.keys():
        y_list = [mod_bases[base][pos] for pos in nuc_pos]
        trace = go.Bar(x=nuc_pos, y=y_list, name=base, marker_color=cmap[base])
        modbases_data.append(trace)
    modbases_layout = go.Layout(
        title="DMS modifications: ",
        xaxis=dict(title="Position"),
        yaxis=dict(title="Abundance"),
        barmode="stack",
    )
    modbases_fig = go.Figure(data=modbases_data, layout=modbases_layout)
    plotly.offline.plot(modbases_fig, filename=fname, auto_open=False)


def plot_mutation_histogram(nuc_pos, num_of_mutations, fname) -> None:
    mut_hist_data = go.Bar(x=nuc_pos, y=num_of_mutations)
    mut_hist_layout = go.Layout(
        title="Mutations: ",
        xaxis=dict(title="Number of mutations per read"),
        yaxis=dict(title="Abundance"),
    )
    mut_hist_fig = go.Figure(data=mut_hist_data, layout=mut_hist_layout)
    plotly.offline.plot(mut_hist_fig, filename=fname, auto_open=False)


def plot_population_avg_old(
    df: pd.DataFrame, name: str, fname: str, plot_sequence=False
) -> None:
    colors = colors_for_sequence(df["nuc"])
    delmut_trace = go.Bar(
        x=list(df["position"]),
        y=list(df["mismatch_del"]),
        text=list(df["nuc"]),
        marker=dict(color=colors),
        showlegend=False,
    )
    mut_trace = go.Bar(
        x=list(df["position"]),
        y=list(df["mismatches"]),
        text=list(df["nuc"]),
        marker=dict(color=colors),
        showlegend=False,
    )
    title1 = "Mismatches + Deletions: " + name
    title2 = "Mismatches: " + name
    mut_fig = make_subplots(rows=2, cols=1, subplot_titles=(title1, title2))
    mut_fig.add_trace(delmut_trace, 1, 1)
    mut_fig.add_trace(mut_trace, 2, 1)
    mut_fig["layout"]["xaxis1"].update(title="Position")
    mut_fig["layout"]["xaxis2"].update(title="Position")
    mut_fig["layout"]["yaxis1"].update(title="Fraction", range=[0, 0.1])
    mut_fig["layout"]["yaxis2"].update(title="Fraction", range=[0, 0.1])
    if plot_sequence:
        seqs = list(df["nuc"])
        if "structure" in df.columns:
            db = list(df["structure"])
        else:
            db = " " * len(seqs)
        mut_fig.update_xaxes(
            tickvals=list(df["position"]),
            ticktext=["%s<br>%s" % (x, y) for (x, y) in zip(seqs, db)],
            tickangle=0,
        )
    plotly.offline.plot(mut_fig, filename=fname, auto_open=False)


def plot_population_avg(
    df: pd.DataFrame, name: str, fname: str, plot_sequence=False
) -> None:
    colors = colors_for_sequence(df["nuc"])
    mut_trace = go.Bar(
        x=list(df["position"]),
        y=list(df["mismatches"]),
        text=list(df["nuc"]),
        marker=dict(color=colors),
        showlegend=False,
    )
    mut_fig_layout = go.Layout(
        title=name,
        xaxis=dict(title="Position"),
        yaxis=dict(title="Fraction", range=[0, 0.1]),
        plot_bgcolor="white",
    )
    mut_fig = go.Figure(data=mut_trace, layout=mut_fig_layout)
    seqs = list(df["nuc"])
    if "structure" in df.columns:
        db = list(df["structure"])
    else:
        db = " " * len(seqs)
    mut_fig.update_yaxes(
        gridcolor="lightgray", linewidth=1, linecolor="black", mirror=True
    )
    mut_fig.update_xaxes(linewidth=1, linecolor="black", mirror=True)
    if plot_sequence:
        mut_fig.update_xaxes(
            tickvals=list(df["position"]),
            ticktext=["%s<br>%s" % (x, y) for (x, y) in zip(seqs, db)],
            tickangle=0,
        )
    plotly.offline.plot(mut_fig, filename=fname, auto_open=False)


# analysis functions ###########################################################


def generate_quality_control_file(mh: MutationHistogram, p):
    file_base_name = (
        p.dirs.bitvector
        + mh.name
        + "_"
        + str(mh.start)
        + "_"
        + str(mh.end)
        + "_"
    )
    qc_filename = file_base_name + "Quality_Control.txt"
    qc_file = open(qc_filename, "w")

    # Read coverage
    qc_file.write(
        mh.name + " has " + str(mh.num_reads) + " reads mapping to it"
    )
    qc_file.write(". This is: ")
    if mh.num_reads < 50000:
        qc_file.write("BAD.\n")
    elif 50000 <= mh.num_reads < 100000:
        qc_file.write("MEDIUM.\n")
    else:
        qc_file.write("GOOD.\n")

    # Signal-noise ratio
    sig_noise = mh.get_signal_to_noise()
    qc_file.write(
        "The signal-to-noise ratio for the sample is: " + str(sig_noise)
    )
    qc_file.write(". This is: ")
    if sig_noise < 0.75:
        qc_file.write("BAD.\n")
    elif 0.75 <= sig_noise < 0.9:
        qc_file.write("MEDIUM.\n")
    else:
        qc_file.write("GOOD.\n")

    # Distribution of coverage
    qc_file.write("Distribution of coverage:\n")
    m = max(mh.cov_bases)
    norm_read_cov = [i / m for i in mh.cov_bases]
    n1, n2, n3 = 0, 0, 0
    for cov in norm_read_cov:
        if cov < 0.5:
            n1 += 1
        elif 0.5 <= cov < 0.75:
            n2 += 1
        elif 0.75 <= cov:
            n3 += 1
    n1 = str(round(n1 * 100 / len(mh.cov_bases), 2))
    n2 = str(round(n2 * 100 / len(mh.cov_bases), 2))
    n3 = str(round(n3 * 100 / len(mh.cov_bases), 2))
    n1_s = "{}% of bases have less than {}% of reads mapping to them\n"
    n1_s = n1_s.format(n1, 50)
    n2_s = "{}% of bases have between {}% and {}% of reads mapping to them\n"
    n2_s = n2_s.format(n2, 50, 75)
    n3_s = "{}% of bases have greater than {}% of reads mapping to them\n\n"
    n3_s = n3_s.format(n3, 75)
    qc_file.write(n1_s)
    qc_file.write(n2_s)
    qc_file.write(n3_s)

    # Info on numbers:
    qc_file.write("FOR REFERENCE:\n")

    # Read coverage
    qc_file.write("Read coverage:\n")
    qc_file.write("Number of reads < 50000: BAD\n")
    qc_file.write("50000 < Number of reads < 100000: MEDIUM\n")
    qc_file.write("Number of reads > 100000: GOOD\n\n")

    # Signal-to-noise ratio
    qc_file.write("Signal-to-noise ratio:\n")
    qc_file.write("Signal-noise ratio < 0.75: BAD\n")
    qc_file.write("0.75 < Signal-noise ratio < 0.9: MEDIUM\n")
    qc_file.write("Signal-noise ratio > 0.9: GOOD\n\n")

    qc_file.write(
        "If you are only interested in the population average"
        + " and not clustering, 1000-10000 reads might be sufficient.\n\n"
    )

    qc_file.close()


def merge_mut_histo_dicts(
    left: Dict[str, MutationHistogram], right: Dict[str, MutationHistogram]
) -> None:
    """
    Merges two mutational histogram dictionaries  The "left" is updated with
    the "right"
    """
    # get common keys between the two dictionaries
    for key in right.keys():
        if key in left.keys():
            left[key].merge(right[key])
        else:
            left[key] = right[key]


def merge_all_merge_mut_histo_dicts(
    mut_histos: List[Dict[str, MutationHistogram]]
) -> Dict[str, MutationHistogram]:
    """
    Merges all mutational histogram dictionaries in the list
    :param mut_histos: list of mutational histogram dictionaries
    :return: merged mutational histogram dictionary
    """
    merged = mut_histos.pop(0)
    for mh in mut_histos:
        merge_mut_histo_dicts(merged, mh)
    return merged
