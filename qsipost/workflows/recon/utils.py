"""
Miscellaneous workflows
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autofunction:: init_discard_repeated_samples_wf
.. autofunction:: init_conform_dwi_wf


"""

import logging

import nipype.interfaces.utility as niu
import nipype.pipeline.engine as pe

from ...interfaces.interchange import recon_workflow_input_fields
from qsipost.interfaces import ConformDwi
from qsipost.interfaces.gradients import RemoveDuplicates
from qsipost.interfaces.mrtrix import MRTrixGradientTable

LOGGER = logging.getLogger("nipype.workflow")


def init_conform_dwi_wf(
    available_anatomical_data, name="conform_dwi", qsirecon_suffix="", params={}
):
    """If data were preprocessed elsewhere, ensure the gradients and images
    conform to LPS+ before running other parts of the pipeline."""
    inputnode = pe.Node(
        niu.IdentityInterface(fields=recon_workflow_input_fields), name="inputnode"
    )
    outputnode = pe.Node(
        niu.IdentityInterface(fields=["dwi_file", "bval_file", "bvec_file", "b_file"]),
        name="outputnode",
    )
    workflow = pe.Workflow(name=name)
    conform = pe.Node(ConformDwi(), name="conform_dwi")
    grad_table = pe.Node(MRTrixGradientTable(), name="grad_table")
    workflow.connect([
        (inputnode, conform, [
            ('dwi_file', 'dwi_file')]),
        (conform, grad_table, [
            ('bval_file', 'bval_file'),
            ('bvec_file', 'bvec_file')]),
        (grad_table, outputnode, [
            ('gradient_file', 'b_file')]),
        (conform, outputnode, [
            ('bval_file', 'bval_file'),
            ('bvec_file', 'bvec_file'),
            ('dwi_file', 'dwi_file')])
    ])  # fmt:skip
    return workflow


def init_discard_repeated_samples_wf(
    available_anatomical_data,
    name="discard_repeats",
    qsirecon_suffix="",
    space="T1w",
    params={},
):
    """Remove a sample if a similar direction/gradient has already been sampled."""
    inputnode = pe.Node(
        niu.IdentityInterface(fields=recon_workflow_input_fields), name="inputnode"
    )
    outputnode = pe.Node(
        niu.IdentityInterface(fields=["dwi_file", "bval_file", "bvec_file", "local_bvec_file"]),
        name="outputnode",
    )
    workflow = pe.Workflow(name=name)

    discard_repeats = pe.Node(RemoveDuplicates(**params), name="discard_repeats")
    workflow.connect([
        (inputnode, discard_repeats, [
            ('dwi_file', 'dwi_file'),
            ('bval_file', 'bval_file'),
            ('bvec_file', 'bvec_file')]),
        (discard_repeats, outputnode, [
            ('dwi_file', 'dwi_file'),
            ('bval_file', 'bval_file'),
            ('bvec_file', 'bvec_file')])
    ])  # fmt:skip

    return workflow
