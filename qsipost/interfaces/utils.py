#!/usr/bin/env python
# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""
Miscellaneous utilities
^^^^^^^^^^^^^^^^^^^^^^^

"""

import os

import nibabel as nb
import numpy as np
import scipy.ndimage as nd
from nipype import logging
from nipype.interfaces import ants
from nipype.interfaces.base import (
    BaseInterfaceInputSpec,
    DynamicTraitedSpec,
    File,
    SimpleInterface,
    TraitedSpec,
    isdefined,
    traits,
)
from nipype.interfaces.io import add_traits
from nipype.utils.filemanip import fname_presuffix

from ..utils.atlases import get_atlases

IFLOGGER = logging.getLogger("nipype.interfaces")


class GetConnectivityAtlasesInputSpec(BaseInterfaceInputSpec):
    atlas_names = traits.List(mandatory=True, desc="atlas names to be used")
    forward_transform = File(exists=True, desc="transform to get atlas into T1w space if desired")
    reference_image = File(exists=True, desc="")
    space = traits.Str("T1w", usedefault=True)


class GetConnectivityAtlasesOutputSpec(TraitedSpec):
    atlas_configs = traits.Dict()
    commands = File()


class GetConnectivityAtlases(SimpleInterface):
    input_spec = GetConnectivityAtlasesInputSpec
    output_spec = GetConnectivityAtlasesOutputSpec

    def _run_interface(self, runtime):
        atlas_names = self.inputs.atlas_names
        atlas_configs = get_atlases(atlas_names)

        if self.inputs.space == "T1w":
            if not isdefined(self.inputs.forward_transform):
                raise Exception("No MNI to T1w transform found in anatomical directory")
            else:
                transform = self.inputs.forward_transform
        else:
            transform = "identity"

        # Transform atlases to match the DWI data
        resample_commands = []
        for atlas_name, atlas_config in atlas_configs.items():
            output_name = fname_presuffix(
                atlas_config["file"], newpath=runtime.cwd, suffix="_to_dwi"
            )
            output_mif = fname_presuffix(
                atlas_config["file"], newpath=runtime.cwd, suffix="_to_dwi.mif", use_ext=False
            )
            output_mif_txt = fname_presuffix(
                atlas_config["file"],
                newpath=runtime.cwd,
                suffix="_mrtrixlabels.txt",
                use_ext=False,
            )
            output_orig_txt = fname_presuffix(
                atlas_config["file"], newpath=runtime.cwd, suffix="_origlabels.txt", use_ext=False
            )

            atlas_configs[atlas_name]["dwi_resolution_file"] = output_name
            atlas_configs[atlas_name]["dwi_resolution_mif"] = output_mif
            atlas_configs[atlas_name]["orig_lut"] = output_mif_txt
            atlas_configs[atlas_name]["mrtrix_lut"] = output_orig_txt
            resample_commands.append(
                _resample_atlas(
                    input_atlas=atlas_config["file"],
                    output_atlas=output_name,
                    transform=transform,
                    ref_image=self.inputs.reference_image,
                )
            )
            label_convert(output_name, output_mif, output_orig_txt, output_mif_txt, atlas_config)

        self._results["atlas_configs"] = atlas_configs
        commands_file = os.path.join(runtime.cwd, "transform_commands.txt")
        with open(commands_file, "w") as f:
            f.write("\n".join(resample_commands))

        self._results["commands"] = commands_file
        return runtime


def _resample_atlas(input_atlas, output_atlas, transform, ref_image):
    xform = ants.ApplyTransforms(
        transforms=[transform],
        reference_image=ref_image,
        input_image=input_atlas,
        output_image=output_atlas,
        interpolation="MultiLabel",
    )
    result = xform.run()

    return result.runtime.cmdline


def label_convert(original_atlas, output_mif, orig_txt, mrtrix_txt, metadata):
    """Create a mrtrix label file from an atlas."""

    with open(mrtrix_txt, "w") as mrtrix_f:
        with open(orig_txt, "w") as orig_f:
            for row_num, (roi_num, roi_name) in enumerate(
                zip(metadata["node_ids"], metadata["node_names"])
            ):
                orig_f.write("{}\t{}\n".format(roi_num, roi_name))
                mrtrix_f.write("{}\t{}\n".format(row_num + 1, roi_name))
    cmd = ["labelconvert", original_atlas, orig_txt, mrtrix_txt, output_mif]
    os.system(" ".join(cmd))


class AddTSVHeaderInputSpec(BaseInterfaceInputSpec):
    in_file = File(exists=True, mandatory=True, desc="input file")
    columns = traits.List(traits.Str, mandatory=True, desc="header for columns")


class AddTSVHeaderOutputSpec(TraitedSpec):
    out_file = File(exists=True, desc="output average file")


class AddTSVHeader(SimpleInterface):
    """Add a header row to a TSV file

    .. testsetup::

    >>> import os
    >>> import pandas as pd
    >>> import numpy as np
    >>> from tempfile import TemporaryDirectory
    >>> tmpdir = TemporaryDirectory()
    >>> os.chdir(tmpdir.name)

    .. doctest::

    An example TSV:

    >>> np.savetxt('data.tsv', np.arange(30).reshape((6, 5)), delimiter='\t')

    Add headers:

    >>> from qsipost.interfaces import AddTSVHeader
    >>> addheader = AddTSVHeader()
    >>> addheader.inputs.in_file = 'data.tsv'
    >>> addheader.inputs.columns = ['a', 'b', 'c', 'd', 'e']
    >>> res = addheader.run()
    >>> pd.read_csv(res.outputs.out_file, sep='\s+', index_col=None,
    ...             engine='python')  # doctest: +NORMALIZE_WHITESPACE
          a     b     c     d     e
    0   0.0   1.0   2.0   3.0   4.0
    1   5.0   6.0   7.0   8.0   9.0
    2  10.0  11.0  12.0  13.0  14.0
    3  15.0  16.0  17.0  18.0  19.0
    4  20.0  21.0  22.0  23.0  24.0
    5  25.0  26.0  27.0  28.0  29.0

    .. testcleanup::

    >>> tmpdir.cleanup()

    """

    input_spec = AddTSVHeaderInputSpec
    output_spec = AddTSVHeaderOutputSpec

    def _run_interface(self, runtime):
        out_file = fname_presuffix(
            self.inputs.in_file, suffix="_motion.tsv", newpath=runtime.cwd, use_ext=False
        )
        data = np.loadtxt(self.inputs.in_file)
        np.savetxt(
            out_file, data, delimiter="\t", header="\t".join(self.inputs.columns), comments=""
        )

        self._results["out_file"] = out_file
        return runtime


class TestInputInputSpec(BaseInterfaceInputSpec):
    test1 = traits.Any()


class TestInput(SimpleInterface):
    input_spec = TestInputInputSpec

    def _run_interface(self, runtime):
        return runtime


class ConcatAffinesInputSpec(DynamicTraitedSpec, BaseInterfaceInputSpec):
    invert = traits.Bool(False, usedefault=True, desc="Invert output transform")


class ConcatAffinesOutputSpec(TraitedSpec):
    out_mat = File(exists=True, desc="Output transform")


class ConcatAffines(SimpleInterface):
    input_spec = ConcatAffinesInputSpec
    output_spec = ConcatAffinesOutputSpec

    def __init__(self, num_affines=0, *args, **kwargs):
        super(ConcatAffines, self).__init__(*args, **kwargs)
        self._num_affines = num_affines
        trait_type = File(exists=True)
        if num_affines == 0:
            add_traits(self.inputs, ["mat_list"], trait_type)
        elif num_affines < 26:
            add_traits(self.inputs, self._get_names(num_affines), trait_type)

    @staticmethod
    def _get_names(num_affines):
        A = ord("A") - 1
        return ["mat_{}to{}".format(chr(X), chr(X + 1)) for X in range(A + num_affines, A, -1)]

    def _run_interface(self, runtime):
        out_mat = os.path.join(runtime.cwd, "concat.mat")
        in_list = [self.inputs.get()[name] for name in self._get_names(self._num_affines)]

        out_xfm = _concat_xfms(in_list, invert=self.inputs.invert)
        np.savetxt(out_mat, out_xfm, fmt=str("%.12g"))

        self._results["out_mat"] = out_mat
        return runtime


def _tpm2roi(
    in_tpm,
    in_mask,
    mask_erosion_mm=None,
    erosion_mm=None,
    mask_erosion_prop=None,
    erosion_prop=None,
    pthres=0.95,
    newpath=None,
):
    """
    Generate a mask from a tissue probability map
    """
    tpm_img = nb.load(in_tpm)
    roi_mask = (tpm_img.get_fdata() >= pthres).astype(np.uint8)

    eroded_mask_file = None
    erode_in = (
        mask_erosion_mm is not None
        and mask_erosion_mm > 0
        or mask_erosion_prop is not None
        and mask_erosion_prop < 1
    )
    if erode_in:
        eroded_mask_file = fname_presuffix(in_mask, suffix="_eroded", newpath=newpath)
        mask_img = nb.load(in_mask)
        mask_data = mask_img.get_fdata().astype(np.uint8)
        if mask_erosion_mm:
            iter_n = max(int(mask_erosion_mm / max(mask_img.header.get_zooms())), 1)
            mask_data = nd.binary_erosion(mask_data, iterations=iter_n)
        else:
            orig_vol = np.sum(mask_data > 0)
            while np.sum(mask_data > 0) / orig_vol > mask_erosion_prop:
                mask_data = nd.binary_erosion(mask_data, iterations=1)

        # Store mask
        eroded = nb.Nifti1Image(mask_data, mask_img.affine, mask_img.header)
        eroded.set_data_dtype(np.uint8)
        eroded.to_filename(eroded_mask_file)

        # Mask TPM data (no effect if not eroded)
        roi_mask[~mask_data] = 0

    # shrinking
    erode_out = (
        erosion_mm is not None and erosion_mm > 0 or erosion_prop is not None and erosion_prop < 1
    )
    if erode_out:
        if erosion_mm:
            iter_n = max(int(erosion_mm / max(tpm_img.header.get_zooms())), 1)
            iter_n = int(erosion_mm / max(tpm_img.header.get_zooms()))
            roi_mask = nd.binary_erosion(roi_mask, iterations=iter_n)
        else:
            orig_vol = np.sum(roi_mask > 0)
            while np.sum(roi_mask > 0) / orig_vol > erosion_prop:
                roi_mask = nd.binary_erosion(roi_mask, iterations=1)

    # Create image to resample
    roi_fname = fname_presuffix(in_tpm, suffix="_roi", newpath=newpath)
    roi_img = nb.Nifti1Image(roi_mask, tpm_img.affine, tpm_img.header)
    roi_img.set_data_dtype(np.uint8)
    roi_img.to_filename(roi_fname)
    return roi_fname, eroded_mask_file or in_mask


def _concat_xfms(in_list, invert):
    transforms = [np.loadtxt(in_mat) for in_mat in in_list]
    out_xfm = transforms.pop(0)
    for xfm in transforms:
        out_xfm = out_xfm.dot(xfm)

    if invert:
        out_xfm = np.linalg.inv(out_xfm)

    return out_xfm
