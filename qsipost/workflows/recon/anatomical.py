#!/usr/bin/env python
# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""
qsipost base reconstruction workflows
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autofunction:: init_qsirecon_wf
.. autofunction:: init_single_subject_wf

"""

from pathlib import Path

import nipype.interfaces.io as nio
from nipype.interfaces import afni, ants, mrtrix3
from nipype.interfaces import utility as niu
from nipype.pipeline import engine as pe
from niworkflows.interfaces.reportlets.registration import SpatialNormalizationRPT
from pkg_resources import resource_filename as pkgrf

from ... import config
from ...engine import Workflow
from ...interfaces.anatomical import QSIPostAnatomicalIngress, UKBAnatomicalIngress
from ...interfaces.ants import ConvertTransformFile
from ...interfaces.bids import ReconDerivativesDataSink
from ...interfaces.freesurfer import find_fs_path
from ...interfaces.gradients import ExtractB0s
from ...interfaces.interchange import (
    FS_FILES_TO_REGISTER,
    anatomical_workflow_outputs,
    qsipost_highres_anatomical_ingressed_fields,
    recon_workflow_input_fields,
)
from ...interfaces.mrtrix import GenerateMasked5tt, ITKTransformConvert, TransformHeader
from ..anatomical.volume import init_output_grid_wf
from qsipost.interfaces.utils import GetConnectivityAtlases

# Required freesurfer files for mrtrix's HSV 5tt generation
HSV_REQUIREMENTS = [
    "mri/aparc+aseg.mgz",
    "mri/brainmask.mgz",
    "mri/transforms/talairach.xfm",
    "surf/lh.white",
    "surf/lh.pial",
    "surf/rh.white",
    "surf/rh.pial",
]

UKB_REQUIREMENTS = ["T1/T1_brain.nii.gz", "T1/T1_brain_mask.nii.gz"]

# Files that must exist if QSIPost ran the anatomical workflow
QSIPOST_ANAT_REQUIREMENTS = [
    "sub-{subject_id}/anat/sub-{subject_id}_desc-brain_mask.nii.gz",
    "sub-{subject_id}/anat/sub-{subject_id}_desc-preproc_T1w.nii.gz",
]

QSIPOST_NORMALIZED_ANAT_REQUIREMENTS = [
    "sub-{subject_id}/anat/sub-{subject_id}_from-T1w_to-MNI152NLin2009cAsym_mode-image_xfm.h5",
    "sub-{subject_id}/anat/sub-{subject_id}_from-MNI152NLin2009cAsym_to-T1w_mode-image_xfm.h5",
]


def init_highres_recon_anatomical_wf(
    subject_id,
    extras_to_make,
    needs_t1w_transform,
):
    """Gather any high-res anatomical data (images, transforms, segmentations) to use
    in recon workflows.

    This workflow searches through input data to see what anatomical data is available.
    The anatomical data may be in a freesurfer directory.

    """

    workflow = Workflow(name="recon_anatomical_wf")
    outputnode = pe.Node(
        niu.IdentityInterface(fields=anatomical_workflow_outputs), name="outputnode"
    )

    # "Gather" the input data. ``status`` is a dict that reflects which anatomical data
    # are present. The anat_ingress_node is a nipype node that ensures that qsipost-style
    # anatomical data is available. In the case where ``pipeline_source`` is not "qsipost",
    # the data is converted in this node to be qsipost-like.
    pipeline_source = config.workflow.recon_input_pipeline
    freesurfer_dir = config.execution.fs_subjects_dir
    if pipeline_source == "qsipost":
        anat_ingress_node, status = gather_qsipost_anatomical_data(subject_id)
    elif pipeline_source == "ukb":
        anat_ingress_node, status = gather_ukb_anatomical_data(subject_id)
    else:
        raise Exception(f"Unknown pipeline source '{pipeline_source}'")
    anat_ingress_node.inputs.infant_mode = config.workflow.infant
    if needs_t1w_transform and not status["has_qsipost_t1w_transforms"]:
        raise Exception("Cannot compute to-template")

    # If there is no high-res anat data in the inputs there may still be an image available
    # from freesurfer. Check for it:
    subject_freesurfer_path = find_fs_path(freesurfer_dir, subject_id)
    status["has_freesurfer"] = subject_freesurfer_path is not None

    # If no high-res are available, we're done here
    if not status["has_qsipost_t1w"] and subject_freesurfer_path is None:
        config.loggers.workflow.warning(
            f"No high-res anatomical data available directly in recon inputs for {subject_id}."
        )
        # If a 5tt image is needed, this is an error
        if "mrtrix_5tt_hsvs" in extras_to_make:
            raise Exception("FreeSurfer data is required to make HSVS 5tt image.")
        workflow.add_nodes([outputnode])
        return workflow, status

    config.loggers.workflow.info(
        f"Found high-res anatomical data in preprocessed inputs for {subject_id}."
    )
    workflow.connect([
        (anat_ingress_node, outputnode,
            [(name, name) for name in qsipost_highres_anatomical_ingressed_fields])])  # fmt:skip

    # grab un-coregistered freesurfer images later use
    if subject_freesurfer_path is not None:
        status["has_freesurfer"] = True
        config.loggers.workflow.info(
            "Freesurfer directory %s exists for %s", subject_freesurfer_path, subject_id
        )
        fs_source = pe.Node(
            nio.FreeSurferSource(subjects_dir=freesurfer_dir, subject_id="sub-" + subject_id),
            name="fs_source",
        )
        workflow.connect([
            (fs_source, outputnode, [
                (field, field) for field in FS_FILES_TO_REGISTER])])  # fmt:skip

    # Do we need to calculate anything else on the
    if "mrtrix_5tt_hsvs" in extras_to_make:
        # Check for specific files needed for HSVs.
        missing_fs_hsvs_files = check_hsv_inputs(Path(subject_freesurfer_path))
        if missing_fs_hsvs_files:
            raise Exception(" ".join(missing_fs_hsvs_files) + "are missing: unable to make a HSV.")

        config.loggers.workflow.info("FreeSurfer data will be used to create a HSVS 5tt image.")
        status["has_freesurfer_5tt_hsvs"] = True
        create_5tt_hsvs = pe.Node(
            GenerateMasked5tt(algorithm="hsvs", in_file=str(subject_freesurfer_path)),
            name="create_5tt_hsvs",
        )
        workflow.connect([
            (create_5tt_hsvs, outputnode, [('out_file', 'fs_5tt_hsvs')])])  # fmt:skip
        ds_qsipost_5tt_hsvs = pe.Node(
            ReconDerivativesDataSink(atlas="hsvs", suffix="dseg", qsirecon_suffix="anat"),
            name="ds_qsipost_5tt_hsvs",
            run_without_submitting=True,
        )
        ds_fs_5tt_hsvs = pe.Node(
            ReconDerivativesDataSink(
                desc="hsvs", space="fsnative", suffix="dseg", qsirecon_suffix="anat"
            ),
            name="ds_fs_5tt_hsvs",
            run_without_submitting=True,
        )

        # Transform the 5tt image so it's registered to the QSIPost AC-PC T1w
        if status["has_qsipost_t1w"]:
            config.loggers.workflow.info(
                "HSVS 5tt imaged will be registered to the " "QSIPost T1w image."
            )
            status["has_qsipost_5tt_hsvs"] = True
            register_fs_to_qsipost_wf = init_register_fs_to_qsipost_wf(
                use_qsipost_reference_mask=True
            )
            apply_header_to_5tt = pe.Node(TransformHeader(), name="apply_header_to_5tt")
            workflow.connect([
                (anat_ingress_node, register_fs_to_qsipost_wf, [
                    ("t1_preproc", "inputnode.qsipost_reference_image"),
                    ("t1_brain_mask", "inputnode.qsipost_reference_mask")]),
                (fs_source, register_fs_to_qsipost_wf, [
                    (field, "inputnode." + field) for field in FS_FILES_TO_REGISTER]),
                (register_fs_to_qsipost_wf, outputnode, [
                    ("outputnode.fs_to_qsipost_transform_mrtrix",
                        "fs_to_qsipost_transform_mrtrix"),
                    ("outputnode.fs_to_qsipost_transform_itk",
                        "fs_to_qsipost_transform_itk")] + [
                    ("outputnode." + field, field) for field in FS_FILES_TO_REGISTER]),
                (create_5tt_hsvs, apply_header_to_5tt, [("out_file", "in_image")]),
                (create_5tt_hsvs, ds_fs_5tt_hsvs, [("out_file", "in_file")]),

                (register_fs_to_qsipost_wf, apply_header_to_5tt, [
                    ("outputnode.fs_to_qsipost_transform_mrtrix", "transform_file")]),
                (apply_header_to_5tt, outputnode, [
                    ("out_image", "qsipost_5tt_hsvs")]),
                (apply_header_to_5tt, ds_qsipost_5tt_hsvs, [("out_image", "in_file")]),
            ])  # fmt:skip
            workflow.__desc__ += "A hybrid surface/volume segmentation was created [Smith 2020]."

    return workflow, status


def gather_ukb_anatomical_data(subject_id):
    """
    Check a UKB directory for the necessary files for recon workflows.

    Parameters
    ----------
    subject_id : str
        List of subject labels

    """
    status = {
        "has_qsipost_5tt_hsvs": False,
        "has_freesurfer_5tt_hsvs": False,
        "has_freesurfer": False,
    }
    recon_input_dir = config.execution.recon_input

    # Check to see if we have a T1w preprocessed by QSIPost
    missing_ukb_anats = check_ukb_anatomical_outputs(recon_input_dir)
    has_t1w = not missing_ukb_anats
    status["has_qsipost_t1w"] = has_t1w
    if missing_ukb_anats:
        config.loggers.workflow.info(f"Missing T1w from UKB session: {recon_input_dir}")
    else:
        config.loggers.workflow.info("Found usable UKB-preprocessed T1w image and mask.")
    anat_ingress = pe.Node(
        UKBAnatomicalIngress(subject_id=subject_id, recon_input_dir=recon_input_dir),
        name="ukb_anat_ingress",
    )

    # I couldn't figure out how to convert UKB transforms to ants. So
    # they're not available for recon workflows for now
    status["has_qsipost_t1w_transforms"] = False
    config.loggers.workflow.info("QSIPost can't read FNIRT transforms from UKB at this time.")

    return anat_ingress, status


def gather_qsipost_anatomical_data(subject_id):
    """
    Gathers the anatomical data from a qsipost input and finds which files are available.


    Parameters
    ----------
    subject_id : str
        List of subject labels

    """
    status = {
        "has_qsipost_5tt_hsvs": False,
        "has_freesurfer_5tt_hsvs": False,
        "has_freesurfer": False,
    }
    recon_input_dir = config.execution.recon_input
    # Check to see if we have a T1w preprocessed by QSIPost
    missing_qsipost_anats = check_qsipost_anatomical_outputs(recon_input_dir, subject_id, "T1w")
    has_qsipost_t1w = not missing_qsipost_anats
    status["has_qsipost_t1w"] = has_qsipost_t1w
    if missing_qsipost_anats:
        config.loggers.workflow.info(
            "Missing T1w QSIPost outputs found: %s", " ".join(missing_qsipost_anats)
        )
    else:
        config.loggers.workflow.info("Found usable QSIPost-preprocessed T1w image and mask.")
    anat_ingress = pe.Node(
        QSIPostAnatomicalIngress(subject_id=subject_id, recon_input_dir=recon_input_dir),
        name="qsipost_anat_ingress",
    )

    # Check if the T1w-to-MNI transforms are in the QSIPost outputs
    missing_qsipost_transforms = check_qsipost_anatomical_outputs(
        recon_input_dir, subject_id, "transforms"
    )
    has_qsipost_t1w_transforms = not missing_qsipost_transforms
    status["has_qsipost_t1w_transforms"] = has_qsipost_t1w_transforms

    if missing_qsipost_transforms:
        config.loggers.workflow.info(
            "Missing T1w QSIPost outputs: %s", " ".join(missing_qsipost_transforms)
        )

    return anat_ingress, status


def check_hsv_inputs(subj_fs_path):
    """Determine if a FreeSurfer directory has the required files for HSV."""
    missing = []
    for requirement in HSV_REQUIREMENTS:
        if not (subj_fs_path / requirement).exists():
            missing.append(requirement)
    return missing


def _check_zipped_unzipped(path_to_check):
    """Check to see if a path exists and warn if it's gzipped."""

    exists = False
    if path_to_check.exists():
        exists = True
    if path_to_check.name.endswith(".gz"):
        nonzipped = str(path_to_check)[:-3]
        if Path(nonzipped).exists():
            config.loggers.workflow.warn(
                "A Non-gzipped input nifti file was found. Consider gzipping %s", nonzipped
            )
            exists = True
    config.loggers.workflow.info(f"CHECKING {path_to_check}: {exists}")
    return exists


def check_qsipost_anatomical_outputs(recon_input_dir, subject_id, anat_type):
    """Determines whether an aligned T1w exists in a qsipost derivatives directory.

    It is possible that:
      - ``--dwi-only`` was used, in which case there is NO T1w available
      - ``--skip-anat-based-spatial-normalization``, there is a T1w but no transform to a template
      - Normal mode, there is a T1w and a transform to template space.
    """
    missing = []
    recon_input_path = Path(recon_input_dir)
    to_check = (
        QSIPOST_ANAT_REQUIREMENTS if anat_type == "T1w" else QSIPOST_NORMALIZED_ANAT_REQUIREMENTS
    )

    for requirement in to_check:
        requirement = requirement.format(subject_id=subject_id)
        t1_version = recon_input_path / requirement
        if _check_zipped_unzipped(t1_version):
            continue

        # Try to see if a T2w version is present
        t2w_version = recon_input_path / requirement.replace("_T1w", "_T2w")
        if _check_zipped_unzipped(t2w_version):
            continue
        missing.append(str(t1_version))

    return missing


def check_ukb_anatomical_outputs(recon_input_dir):
    """Check for required files under a UKB session directory.

    Parameters:

    recon_input_dir: pathlike
        Path to a UKB subject directory (eg 1234567_2_0)
    """
    missing = []
    recon_input_path = Path(recon_input_dir)
    for requirement in UKB_REQUIREMENTS:
        if not (recon_input_path / requirement).exists():
            missing.append(str(requirement))
    return missing


def init_register_fs_to_qsipost_wf(
    use_qsipost_reference_mask=False, name="register_fs_to_qsipost_wf"
):
    """Registers a T1w images from freesurfer to another image and transforms"""
    inputnode = pe.Node(
        niu.IdentityInterface(
            fields=FS_FILES_TO_REGISTER + ["qsipost_reference_image", "qsipost_reference_mask"]
        ),
        name="inputnode",
    )
    outputnode = pe.Node(
        niu.IdentityInterface(
            fields=FS_FILES_TO_REGISTER
            + ["fs_to_qsipost_transform_itk", "fs_to_qsipost_transform_mrtrix"]
        ),
        name="outputnode",
    )
    workflow = Workflow(name=name)
    workflow.__desc__ = "FreeSurfer outputs were registered to the QSIPost outputs."

    # Convert the freesurfer inputs so we can register them with ANTs
    convert_fs_brain = pe.Node(
        mrtrix3.MRConvert(out_file="fs_brain.nii", args="-strides -1,-2,3"),
        name="convert_fs_brain",
    )

    # Register the brain to the QSIPost reference
    ants_settings = pkgrf("qsipost", "data/freesurfer_to_qsipost.json")
    register_to_qsipost = pe.Node(
        ants.Registration(from_file=ants_settings), name="register_to_qsipost"
    )

    # If there is a mask for the QSIPost reference image, use it
    if use_qsipost_reference_mask:
        workflow.connect(inputnode, "qsipost_reference_mask",
                         register_to_qsipost, "fixed_image_masks")  # fmt:skip

    # The more recent ANTs mat format isn't compatible with transformconvert.
    # So convert it to ANTs text format with ConvertTransform
    convert_ants_transform = pe.Node(
        ConvertTransformFile(dimension=3), name="convert_ants_transform"
    )

    # Convert from ANTs text format to MRtrix3 format
    convert_ants_to_mrtrix_transform = pe.Node(
        ITKTransformConvert(), name="convert_ants_to_mrtrix_transform"
    )

    # Adjust the headers of all the input images so they're aligned to the qsipost ref
    transform_nodes = {}
    for image_name in FS_FILES_TO_REGISTER:
        transform_nodes[image_name] = pe.Node(TransformHeader(), name="transform_" + image_name)
        workflow.connect([
            (inputnode, transform_nodes[image_name], [(image_name, "in_image")]),
            (convert_ants_to_mrtrix_transform,
             transform_nodes[image_name], [("out_transform", "transform_file")]),
            (transform_nodes[image_name], outputnode, [("out_image", image_name)])
        ])  # fmt:skip

    workflow.connect([
        (inputnode, convert_fs_brain, [
            ("brain", "in_file")]),
        (inputnode, register_to_qsipost, [
            ("qsipost_reference_image", "fixed_image")]),
        (convert_fs_brain, register_to_qsipost, [
            ("out_file", "moving_image")]),
        (register_to_qsipost, convert_ants_transform, [
            (("forward_transforms", _get_first), "in_transform")]),
        (register_to_qsipost, outputnode, [
            ("composite_transform", "fs_to_qsipost_transform_itk")]),
        (convert_ants_transform, convert_ants_to_mrtrix_transform, [
            ("out_transform", "in_transform")]),
        (convert_ants_to_mrtrix_transform, outputnode,
         [("out_transform", "fs_to_qsipost_transform_mrtrix")])
    ])  # fmt:skip

    return workflow


def init_dwi_recon_anatomical_workflow(
    atlas_names,
    has_qsipost_5tt_hsvs,
    needs_t1w_transform,
    has_freesurfer_5tt_hsvs,
    has_qsipost_t1w,
    has_qsipost_t1w_transforms,
    has_freesurfer,
    extras_to_make,
    name,
    prefer_dwi_mask=False,
):
    """Ensure that anatomical data is available for the reconstruction workflows.

    This workflow calculates images/transforms that require a DWI spatial reference.
    Specifically, three additional features are added:

      * ``"dwi_mask"``: a brain mask in the voxel space of the DWI
      * ``"atlas_configs"``: A dictionary used by connectivity workflows to get
        brain parcellations.
      * ``"odf_rois"``: An image with some interesting ROIs for plotting ODFs

    Parameters:
    ===========
        has_qsipost_5tt_hsvs:
        has_freesurfer_5tt_hsvs: True,
        has_qsipost_t1w:
        has_qsipost_t1w_transforms: True}
    """
    # Inputnode holds data from the T1w-based anatomical workflow
    inputnode = pe.Node(
        niu.IdentityInterface(fields=recon_workflow_input_fields), name="inputnode"
    )
    connect_from_inputnode = set(recon_workflow_input_fields)
    # Buffer to hold the anatomical files that are calculated here
    buffernode = pe.Node(
        niu.IdentityInterface(fields=recon_workflow_input_fields), name="buffernode"
    )
    connect_from_buffernode = set()
    b0_threshold = config.workflow.b0_threshold

    def _get_source_node(fieldname):
        if fieldname in connect_from_inputnode:
            return inputnode
        if fieldname in connect_from_buffernode:
            return buffernode
        raise Exception("Can't determine location of " + fieldname)

    def _exchange_fields(fields):
        connect_from_inputnode.difference_update(fields)
        connect_from_buffernode.update(fields)

    # These are always created here
    _exchange_fields(["dwi_mask", "atlas_configs", "odf_rois", "resampling_template"])

    outputnode = pe.Node(
        niu.IdentityInterface(fields=recon_workflow_input_fields), name="outputnode"
    )
    workflow = Workflow(name=name)
    skull_strip_method = "antsBrainExtraction"
    desc = ""

    def _get_status():
        return {
            "has_qsipost_5tt_hsvs": has_qsipost_5tt_hsvs,
            "has_freesurfer_5tt_hsvs": has_freesurfer_5tt_hsvs,
            "has_qsipost_t1w": has_qsipost_t1w,
            "has_qsipost_t1w_transforms": has_qsipost_t1w_transforms,
        }

    reference_grid_wf = init_output_grid_wf()
    workflow.connect([
        (inputnode, reference_grid_wf, [
            ('template_image', 'inputnode.template_image'),
            ('dwi_ref', 'inputnode.input_image')]),
        (reference_grid_wf, buffernode, [
            ('outputnode.grid_image', 'resampling_template')])
    ])  # fmt:skip

    # Missing Freesurfer AND QSIPost T1ws, or the user wants a DWI-based mask
    if not (has_qsipost_t1w or has_freesurfer) or prefer_dwi_mask:
        desc += (
            "No T1w weighted images were available for masking, so a mask "
            "was estimated based on the b=0 images in the DWI data itself."
        )
        extract_b0s = pe.Node(ExtractB0s(b0_threshold=b0_threshold), name="extract_b0s")
        mask_b0s = pe.Node(afni.Automask(outputtype="NIFTI_GZ"), name="mask_b0s")
        workflow.connect([
            (inputnode, extract_b0s, [
                ("dwi_file", "dwi_series"),
                ("bval_file", "bval_file")]),
            (extract_b0s, mask_b0s, [("b0_series", "in_file")]),
            (mask_b0s, outputnode, [("out_file", "dwi_mask")]),
            (inputnode, outputnode, [(field, field) for field in connect_from_inputnode])
        ])  # fmt:skip
        return workflow, _get_status()

    # No data from QSIPost was available, BUT we have freesurfer! register it and
    # get the brain, masks and possibly a to-MNI transform.
    # --> If has_freesurfer AND has qsipost_t1w, the necessary files were created earlier
    elif has_freesurfer and not has_qsipost_t1w:
        fs_source = pe.Node(
            nio.FreeSurferSource(subjects_dir=config.execution.fs_subjects_dir), name="fs_source"
        )
        # Register the FreeSurfer brain to the DWI reference
        desc += (
            "A brainmasked T1w image from FreeSurfer was registered to the "
            "preprocessed DWI data. Brainmasks from FreeSurfer were used in all "
            "subsequent reconstruction steps. "
        )

        # Move these fields to the buffernode
        _exchange_fields(
            FS_FILES_TO_REGISTER
            + [
                "t1_brain_mask",
                "t1_preproc",
                "fs_to_qsipost_transform_mrtrix",
                "fs_to_qsipost_transform_itk",
            ]
        )

        # Perform the registration and connect the outputs to buffernode
        # NOTE: using FreeSurfer "brain" image as t1_preproc and aseg as the brainmask
        has_qsipost_t1w = True
        register_fs_to_qsipost_wf = init_register_fs_to_qsipost_wf(
            use_qsipost_reference_mask=False
        )
        workflow.connect([
            (inputnode, fs_source, [("subject_id", "subject_id")]),
            (inputnode, register_fs_to_qsipost_wf, [
                ("dwi_ref", "inputnode.qsipost_reference_image")]),
            (fs_source, register_fs_to_qsipost_wf, [
                (field, "inputnode." + field) for field in FS_FILES_TO_REGISTER]),
            (register_fs_to_qsipost_wf, buffernode, [
                ("outputnode.brain", "t1_preproc"),
                ("outputnode.aseg", "t1_brain_mask"),
                ("outputnode.fs_to_qsipost_transform_mrtrix",
                    "fs_to_qsipost_transform_mrtrix"),
                ("outputnode.fs_to_qsipost_transform_itk",
                    "fs_to_qsipost_transform_itk")] + [
                ("outputnode." + field, field) for field in FS_FILES_TO_REGISTER]),
        ])  # fmt:skip

    # Do we need to transform the 5tt hsvs from fsnative?
    if "mrtrix_5tt_hsvs" in extras_to_make and not has_qsipost_5tt_hsvs:
        # Transform the 5tt image so it's registered to the QSIPost AC-PC T1w
        config.loggers.workflow.info(
            "HSVS 5tt imaged will be registered to the " "QSIPost dwiref image."
        )
        _exchange_fields(["qsipost_5tt_hsvs"])
        if not has_freesurfer_5tt_hsvs:
            raise Exception("The 5tt image in fsnative should have been created by now")
        apply_header_to_5tt_hsvs = pe.Node(TransformHeader(), name="apply_header_to_5tt_hsvs")
        ds_qsipost_5tt_hsvs = pe.Node(
            ReconDerivativesDataSink(
                atlas="hsvs",
                suffix="dseg",
                qsirecon_suffix="anat",
            ),
            name="ds_qsipost_5tt_hsvs",
            run_without_submitting=True,
        )
        workflow.connect([
            (inputnode, apply_header_to_5tt_hsvs, [("fs_5tt_hsvs", "in_image")]),
            (apply_header_to_5tt_hsvs, buffernode, [
                ("out_image", "qsipost_5tt_hsvs")]),
            (apply_header_to_5tt_hsvs, ds_qsipost_5tt_hsvs, [("out_image", "in_file")]),
        ])  # fmt:skip
        desc += "A hybrid surface/volume segmentation was created [Smith 2020]."

    # If we have transforms to the template space, use them to get ROIs/atlases
    # if not has_qsipost_t1w_transforms and has_qsipost_t1w:
    #     desc += "In order to warp brain parcellations from template space into " \
    #         "alignment with the DWI data, the DWI-aligned FreeSurfer brain was " \
    #         "registered to template space. "

    #     # We now have qsipost t1w and transforms!!
    #     has_qsipost_t1w = has_qsipost_t1w_transforms = True
    #     # Calculate the transforms here:
    #     has_qsipost_t1w_transforms = True
    #     _exchange_fields(['t1_2_mni_forward_transform', 't1_2_mni_reverse_transform'])
    #     t1_2_mni = pe.Node(
    #         get_t1w_registration_node(
    #             infant_mode, sloppy or not atlas_names, omp_nthreads),
    #         name="t1_2_mni")
    #     workflow.connect([
    #         (_get_source_node("t1_preproc"), t1_2_mni, [('t1_preproc', 'moving_image')]),
    #         (t1_2_mni, buffernode, [
    #             ("composite_transform", "t1_2_mni_forward_transform"),
    #             ("inverse_composite_transform", "t1_2_mni_reverse_transform")
    #         ])
    #     ])  # fmt:skip
    #     # TODO: add datasinks here

    # Check the status of the T1wACPC-to-template transforms
    if needs_t1w_transform:
        if has_qsipost_t1w_transforms:
            config.loggers.workflow.info("Found T1w-to-template transforms from QSIPost")
            desc += (
                "T1w-based spatial normalization calculated during "
                "preprocessing was used to map atlases from template space into "
                "alignment with DWIs."
            )
        else:
            raise Exception(
                "Reconstruction workflow requires a T1wACPC-to-template transform. "
                "None were found."
            )

    # Simply resample the T1w mask into the DWI resolution. This was the default
    # up to version 0.14.3
    if has_qsipost_t1w and not prefer_dwi_mask:
        desc += "Brainmasks from {} were used in all " "subsequent reconstruction steps.".format(
            skull_strip_method
        )
        # Resample anat mask
        resample_mask = pe.Node(
            ants.ApplyTransforms(
                dimension=3, transforms=["identity"], interpolation="NearestNeighbor"
            ),
            name="resample_mask",
        )

        workflow.connect([
            (inputnode, resample_mask, [
                ("t1_brain_mask", "input_image"),
                ("dwi_ref", "reference_image")]),
            (resample_mask, buffernode, [("output_image", "dwi_mask")])
        ])  # fmt:skip

    if has_qsipost_t1w_transforms:
        config.loggers.workflow.info("Transforming ODF ROIs into DWI space for visual report.")
        # Resample ROI targets to DWI resolution for ODF plotting
        crossing_rois_file = pkgrf("qsipost", "data/crossing_rois.nii.gz")
        odf_rois = pe.Node(
            ants.ApplyTransforms(interpolation="MultiLabel", dimension=3), name="odf_rois"
        )
        odf_rois.inputs.input_image = crossing_rois_file
        workflow.connect([
            (_get_source_node('t1_2_mni_reverse_transform'), odf_rois, [
                ('t1_2_mni_reverse_transform', 'transforms')]),
            (inputnode, odf_rois, [
                ("dwi_file", "reference_image")]),
            (odf_rois, buffernode, [("output_image", "odf_rois")])
        ])  # fmt:skip

        # Similarly, if we need atlases, transform them into DWI space
        if atlas_names:
            desc += (
                "Cortical parcellations were mapped from template space to DWIS "
                "using the T1w-based spatial normalization. "
            )

            # Resample all atlases to dwi_file's resolution
            get_atlases = pe.Node(
                GetConnectivityAtlases(atlas_names=atlas_names),
                name="get_atlases",
                run_without_submitting=True,
            )
            workflow.connect([
                (_get_source_node('t1_2_mni_reverse_transform'), get_atlases, [
                    ('t1_2_mni_reverse_transform', 'forward_transform')]),
                (get_atlases, buffernode, [
                    ("atlas_configs", "atlas_configs")]),
                (inputnode, get_atlases, [
                    ('dwi_file', 'reference_image')])
            ])  # fmt:skip

        for atlas in atlas_names:
            workflow.connect([
                (
                    get_atlases,
                    pe.Node(
                        ReconDerivativesDataSink(
                            atlas=atlas,
                            suffix="dseg",
                            compress=True,
                            qsirecon_suffix="anat"),
                        name='dsatlas_' + atlas,
                        run_without_submitting=True), [
                            (
                                ('atlas_configs',
                                 _get_resampled, atlas, 'dwi_resolution_file'),
                                'in_file')]),
                (
                    get_atlases,
                    pe.Node(
                        ReconDerivativesDataSink(
                            atlas=atlas,
                            suffix="dseg",
                            extension=".mif.gz",
                            compress=True,
                            qsirecon_suffix="anat"),
                        name='dsatlas_mifs_' + atlas,
                        run_without_submitting=True), [
                            (
                                ('atlas_configs',
                                 _get_resampled, atlas, 'dwi_resolution_mif'),
                                'in_file')]),
                (
                    get_atlases,
                    pe.Node(
                        ReconDerivativesDataSink(
                            atlas=atlas,
                            extension=".txt",
                            suffix="dseg",
                            qsirecon_suffix="anat"),
                        name='dsatlas_mrtrix_lut_' + atlas,
                        run_without_submitting=True), [
                            (
                                ('atlas_configs',
                                 _get_resampled, atlas, 'mrtrix_lut'),
                                'in_file')]),
                (
                    get_atlases,
                    pe.Node(
                        ReconDerivativesDataSink(
                            atlas=atlas,
                            extension=".txt",
                            suffix="dseg",
                            qsirecon_suffix="anat"),
                        name='dsatlas_orig_lut_' + atlas,
                        run_without_submitting=True), [
                            (
                                ('atlas_configs',
                                 _get_resampled, atlas, 'orig_lut'),
                                'in_file')]),
            ])  # fmt:skip

        # Fill in the atlas datasinks
        for node in workflow.list_node_names():
            node_suffix = node.split(".")[-1]
            if node_suffix.startswith("dsatlas_"):
                workflow.connect(
                    inputnode, 'dwi_file', workflow.get_node(node), 'source_file')  # fmt:skip

    if "mrtrix_5tt_hsv" in extras_to_make and not has_qsipost_5tt_hsvs:
        raise Exception("Unable to create a 5tt HSV image given input data.")

    # Directly connect anything from the inputs that we haven't created here
    workflow.connect([
        (inputnode, outputnode, [(name, name) for name in connect_from_inputnode]),
        (buffernode, outputnode, [(name, name) for name in connect_from_buffernode])
    ])  # fmt:skip
    return workflow, _get_status()


def _get_first(item):
    if isinstance(item, (list, tuple)):
        return item[0]
    return item


def _get_resampled(atlas_configs, atlas_name, to_retrieve):
    return atlas_configs[atlas_name][to_retrieve]


def get_t1w_registration_node(infant_mode, sloppy, omp_nthreads):

    # Gets an ants interface for t1w-based normalization
    if sloppy:
        config.loggers.workflow.info("Using QuickSyN")
        # Requires a warp file: make an inaccurate one
        settings = pkgrf("qsipost", "data/quick_syn.json")
        t1_2_mni = pe.Node(
            SpatialNormalizationRPT(
                float=True,
                generate_report=True,
                settings=[settings],
            ),
            name="t1_2_mni",
            n_procs=omp_nthreads,
            mem_gb=2,
        )
    else:
        t1_2_mni = pe.Node(
            SpatialNormalizationRPT(
                float=True,
                generate_report=True,
                flavor="precise",
            ),
            name="t1_2_mni",
            n_procs=omp_nthreads,
            mem_gb=2,
        )
        # Get the template image
    if not infant_mode:
        ref_img_brain = pkgrf("qsipost", "data/mni_1mm_t1w_lps_brain.nii.gz")
    else:
        ref_img_brain = pkgrf("qsipost", "data/mni_1mm_t1w_lps_brain_infant.nii.gz")

    t1_2_mni.inputs.template = "MNI152NLin2009cAsym"
    t1_2_mni.inputs.reference_image = ref_img_brain
    t1_2_mni.inputs.orientation = "LPS"
    return t1_2_mni
