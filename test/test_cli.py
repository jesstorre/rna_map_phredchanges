"""
test cli interface
"""
import os
import shutil
import pytest
from click.testing import CliRunner
from dreem.run import validate_inputs, validate_fasta_file, main
from dreem.logger import setup_applevel_logger
from dreem.exception import DREEMInputException

TEST_DIR = os.path.dirname(os.path.realpath(__file__))


def get_test_inputs_paired():
    """
    Get the test inputs
    """
    test_data_dir = os.path.join(TEST_DIR, "resources", "case_1")
    return {
        "fasta": test_data_dir + "/test.fasta",
        "fastq1": test_data_dir + "/test_mate1.fastq",
        "fastq2": test_data_dir + "/test_mate2.fastq",
    }


def remove_directories(cur_dir):
    """
    Remove the directory for testing
    """
    shutil.rmtree(os.path.join(cur_dir, "input"))
    shutil.rmtree(os.path.join(cur_dir, "log"))
    shutil.rmtree(os.path.join(cur_dir, "output"))


def test_input_validation():
    """
    test input validation
    """
    p = get_test_inputs_paired()
    ins = validate_inputs(p["fasta"], p["fastq1"], "", "")
    assert p["fasta"] == ins.fasta
    assert ins.csv == ""
    assert ins.is_paired() == False
    assert ins.supplied_csv() == False

    # check to make sure we get the proper errors for supplying file that does
    # not exist
    with pytest.raises(DREEMInputException) as exc_info:
        validate_inputs(p["fasta"], "", "", "")
    assert exc_info.value.args[0] == "fastq1 file: does not exist !"
    with pytest.raises(DREEMInputException) as exc_info:
        validate_inputs("fake_path", p["fastq1"], "", "")
    assert exc_info.value.args[0] == "fasta file: does not exist fake_path!"
    with pytest.raises(DREEMInputException) as exc_info:
        validate_inputs(p["fasta"], p["fastq1"], "fake_path", "")
    assert exc_info.value.args[0] == "fastq2 file: does not exist fake_path!"
    with pytest.raises(DREEMInputException) as exc_info:
        validate_inputs(p["fasta"], p["fastq1"], "", "fake_path")
    assert exc_info.value.args[0] == "csv file: does not exist !"


# TODO create these files or maybe grab them from the server repo?
def _test_fasta_checks():
    fasta_test_path = TEST_DIR + "/resources/test_fastas/"
    path = fasta_test_path + "blank_line.fasta"
    with pytest.raises(DREEMInputException) as exc_info:
        validate_fasta_file(path)
    assert (
        exc_info.value.args[0]
        == "blank line found on ln: 1. These are not allowed in fastas."
    )
    path = fasta_test_path + "incorrect_format.fasta"
    with pytest.raises(DREEMInputException) as exc_info:
        validate_fasta_file(path)
    assert (
        exc_info.value.args[0]
        == "reference sequence names are on line zero and even numbers. line 0 "
        "has value which is not correct format in the fasta"
    )
    path = fasta_test_path + "incorrect_sequence.fasta"
    with pytest.raises(DREEMInputException) as exc_info:
        validate_fasta_file(path)
    print(exc_info)


def test_cli_single():
    """
    test running the program
    """
    path = TEST_DIR + "/resources/case_unit/"
    runner = CliRunner()
    result = runner.invoke(
        main, ["-fa", f"{path}/test.fasta", "-fq1", f"{path}/test_mate1.fastq"]
    )
    assert result.exit_code == 0
    assert os.path.isfile(f"output/test_mate1.fastq.dreem")
    remove_directories(os.getcwd())
