#!/bin/bash

cat << DOC

Reconstruction workflow tests
=============================

All supported reconstruction workflows get tested

This tests the following features:
 - pyAFQ pipeline with tractography done in mrtrix

Inputs:
-------

 - qsipost multi shell results (data/DSDTI_fmap)

DOC
set +e
source ./get_data.sh
TESTDIR=${PWD}
get_config_data ${TESTDIR}
get_bids_data ${TESTDIR} multishell_output
CFG=${TESTDIR}/data/nipype.cfg
EDDY_CFG=${TESTDIR}/data/eddy_config.json
export FS_LICENSE=${TESTDIR}/data/license.txt

# Test mrtrix_multishell_msmt_pyafq_tractometry
TESTNAME=mrtrix_multishell_msmt_pyafq_tractometry_test
setup_dir ${TESTDIR}/${TESTNAME}
TEMPDIR=${TESTDIR}/${TESTNAME}/work
OUTPUT_DIR=${TESTDIR}/${TESTNAME}/derivatives
BIDS_INPUT_DIR=${TESTDIR}/data/multishell_output/qsipost
QSIPOST_CMD=$(run_qsipost_cmd ${BIDS_INPUT_DIR} ${OUTPUT_DIR})

${QSIPOST_CMD}  \
	 -w ${TEMPDIR} \
	 --recon-input ${BIDS_INPUT_DIR} \
	 --sloppy \
	 --recon-spec mrtrix_multishell_msmt_pyafq_tractometry \
	 --recon-only \
	 -vv