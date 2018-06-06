##################################################
# Import Own Assets
##################################################
from hyperparameter_hunter.settings import G, ASSETS_DIRNAME, RESULT_FILE_SUB_DIR_PATHS
from hyperparameter_hunter.reporting import ReportingHandler
from hyperparameter_hunter.key_handler import CrossExperimentKeyMaker
from hyperparameter_hunter.utils.file_utils import read_json
from hyperparameter_hunter.utils.general_utils import type_val
from hyperparameter_hunter.utils.result_utils import format_predictions, default_do_full_save

##################################################
# Import Miscellaneous Assets
##################################################
from datetime import datetime
from inspect import signature, getfullargspec, isclass
import numpy as np
import os
import os.path
import pandas as pd
import shutil

##################################################
# Import Learning Assets
##################################################
from sklearn.model_selection import KFold


class Environment():
    DEFAULT_PARAMS = dict(
        environment_params_path=None,
        root_results_path=None,

        target_column='target',
        id_column=None,
        do_predict_proba=False,
        prediction_formatter=format_predictions,
        metrics_map=None,
        metrics_params=dict(),

        cross_validation_type=KFold,
        runs=1,
        global_random_seed=32,
        random_seeds=None,
        random_seed_bounds=[0, 100000],
        cross_validation_params=dict(),

        verbose=True,
        file_blacklist=None,
        reporting_handler_params=dict(
            # reporting_type='logging',
            heartbeat_path=None,
            float_format='{:.5f}',
            console_params=None,
            heartbeat_params=None
        ),
        to_csv_params=dict(),
        do_full_save=default_do_full_save,
    )

    def __init__(
            self,
            train_dataset,  # TODO: Allow providing separate train_input, train_target dataframes, or the full df
            environment_params_path=None,
            *,  # FLAG: ORIGINAL
            # *args,  # FLAG: TEST AUTODOCS COMPATIBILITY
            root_results_path=None,
            holdout_dataset=None,  # TODO: Allow providing separate holdout_input, holdout_target dataframes, or the full df
            test_dataset=None,  # TODO: Allow providing separate test_input, test_target dataframes, or the full df

            target_column=None,
            id_column=None,
            do_predict_proba=None,
            prediction_formatter=None,
            metrics_map=None,
            metrics_params=None,

            cross_validation_type=None,
            runs=None,
            global_random_seed=None,
            random_seeds=None,
            random_seed_bounds=None,
            cross_validation_params=None,

            verbose=None,
            file_blacklist=None,
            reporting_handler_params=None,
            to_csv_params=None,
            do_full_save=None,
            experiment_callbacks=None
    ):
        """Class to organize the parameters that allow Experiments to be fairly compared

        Parameters
        ----------
        train_dataset: Pandas.DataFrame, or str path
            The training data for the experiment. Will be split into train/holdout data, if applicable, and train/validation data
            if cross-validation is to be performed. If str, will attempt to read file at path via :func:`pandas.read_csv`
        environment_params_path: String path, or None, default=None
            If not None and is valid .json filepath containing an object (dict), the file's contents are treated as the default
            values for all keys that match any of the below kwargs used to initialize :class:`Environment`
        root_results_path: String path, or None, default=None
            If valid directory path and the results directory has not yet been created, it will be created here. If this does not
            end with <ASSETS_DIRNAME>, it will be appended. If <ASSETS_DIRNAME>
            already exists at this path, new results will also be stored here. If None or invalid, results will not be stored
        holdout_dataset: Pandas.DataFrame, callable, str path, or None, default=None
            If pd.DataFrame, this is the holdout dataset. If callable, expects a function that takes (self.train: DataFrame,
            self.target_column: str) as input and returns the new (self.train: DataFrame, self.holdout: DataFrame). If str,
            will attempt to read file at path via :func:`pandas.read_csv`. Else, there is no holdout set
        test_dataset: Pandas.DataFrame, str path, or None, default=None
            The testing data for the experiment. Structure should be identical to that of train_dataset, except its
            target_column column can be empty or non-existent, because test_dataset predictions will never be evaluated. If str,
            will attempt to read file at path via :func:`pandas.read_csv`
        target_column: str, default='target'
            Str denoting the column name in all provided datasets (except test) that contains the target output
        id_column: str, or None, default=None
            If not None, str denoting the column name in all provided datasets that contains sample IDs
        do_predict_proba: Boolean, default=False
            If True, :meth:`models.Model.fit` will call :meth:`models.Model.model.predict_proba`. Else, it will
            call :meth:`models.Model.model.predict`
        prediction_formatter: Callable, or None, default=None
            If callable, expected to have same signature as :func:`environment_hander.format_predictions`. That is, the callable
            will receive (raw_predictions: np.array, dataset_df: pd.DataFrame, target_column: str, id_column: str or None) as
            input and should return a properly formatted prediction DataFrame. The callable uses raw_predictions as the content,
            dataset_df to provide any id column, and target_column to identify the column in which to place raw_predictions
            # TODO: Move metrics_map/metrics_params closer to the top of arguments, since one is required
        metrics_map: Dict, List, or None, default=None
            Specifies all metrics to be used by their id keys, along with a means to compute the metric. If list, all values must
            be strings that are attributes in :mod:`sklearn.metrics`. If dict, key/value pairs must be of the form:
            (<id>, <callable/None/str sklearn.metrics attribute>), where "id" is a str name for the metric. Its corresponding
            value must be one of: 1) a callable to calculate the metric, 2) None if the "id" key is an attribute in
            `sklearn.metrics` and should be used to fetch a callable, 3) a string that is an attribute in `sklearn.metrics` and
            should be used to fetch a callable. Metric callable functions should expect inputs of form (target, prediction), and
            should return floats. See `metrics_params` for details on how these two are related
        metrics_params: Dict, or None, default=dict()
            Dictionary of extra parameters to provide to :meth:`metrics.ScoringMixIn.__init__`. `metrics_map` must be provided
            either 1) as an input kwarg to :meth:`Environment.__init__` (see `metrics_map`), or 2) as a key in `metrics_params`,
            but not both. An Exception will be raised if both are given, or if neither is given
            # TODO: Move metrics_map/metrics_params closer to the top of arguments, since one is required
        cross_validation_type: Class, default=:class:`sklearn.model_selection.KFold`
            The class to define cross-validation splits. It must implement the following methods: [`__init__`, `split`]. If
            using a custom class, see the following tested `sklearn` classes for proper implementations: [`KFold`,
            `StratifiedKFold`, `RepeatedKFold`, `RepeatedStratifiedKFold`]. The arguments provided to
            :meth:`cross_validation_type.__init__` will be :attr:`Environment.cross_validation_params`, which should include the
            following: ["n_splits" <int>, "n_repeats" <int> (if applicable)]. :meth:`cross_validation_type.split` will receive the
            following arguments: [:attr:`BaseExperiment.train_input_data`, :attr:`BaseExperiment.train_target_data`]
        runs: Int, default=1
            The number of times to fit a model within each fold to perform multiple-run-averaging with different random seeds
        global_random_seed: Int, default=32
            The initial random seed used just before generating an Experiment's random_seeds. This ensures consistency for
            `random_seeds` between Experiments, without having to explicitly provide it here
        random_seeds: None, or List, default=None
            If None, `random_seeds` of the appropriate shape will be created automatically. Else, must be a list of ints of shape
            (`cross_validation_params['n_repeats']`, `cross_validation_params['n_splits']`, `runs`). If `cross_validation_params`
            does not have the key `n_repeats` (because standard cross-validation is being used), the value will default to 1.
            See :meth:`experiments.BaseExperiment.random_seed_initializer` for more info on the expected shape
        random_seed_bounds: List, default=[0, 100000]
            A list containing two integers: the lower and upper bounds, respectively, for generating an Experiment's random seeds
            in :meth:`experiments.BaseExperiment.random_seed_initializer`. Generally, leave this kwarg alone
        cross_validation_params: dict, or None, default=dict()
            Dict of parameters provided upon initialization of cross_validation_type. Keys may be any args accepted by
            :meth:`cross_validation_type.__init__`. Number of fold splits must be provided here via "n_splits", and number of
            repeats (if applicable according to `cross_validation_type`) must be provided via "n_repeats"
        verbose: Boolean, default=True
            Verbosity of printing for any experiments performed while this Environment is active
        file_blacklist: List of str, or None, or 'ALL', default=None
            If list of str, the result files named within are not saved to their respective directory in
            "<ASSETS_DIRNAME>/Experiments". If None, all result files are saved. If 'ALL', nothing at all will be saved for the
            Experiments. For info on acceptable values, see :func:`hyperparameter_hunter.environment.validate_file_blacklist`
        reporting_handler_params: Dict, default=dict()
            Parameters passed to initialize :class:`reporting.ReportingHandler`
        to_csv_params: Dict, default=dict()
            Parameters passed to the calls to :meth:`pandas.frame.DataFrame.to_csv` in :mod:`recorders`. In particular,
            this is where an Experiment's final prediction files are saved, so the values here will affect the format of the .csv
            prediction files. Warning: If `to_csv_params` contains the key "path_or_buf", it will be removed. Otherwise, all
            items are supplied directly to :meth:`to_csv`, including kwargs it might not be expecting if they are given
        do_full_save: None, or callable, default=:func:`utils.result_utils.default_do_full_save`
            If callable, expected to take an Experiment's result description dict as input and return a boolean. If None, treated
            as a callable that returns True
        experiment_callbacks: :class:`LambdaCallback`, list of :class:`LambdaCallback`, or None, default=None
            If not None, should be a :class:`LambdaCallback` produced by :func:`callbacks.bases.lambda_callback`, or a list of
            such classes. The contents will be added to the MRO of the executed Experiment class by
            :class:`experiment_core.ExperimentMeta` at `__call__` time, making `experiment_callbacks` new base classes of the
            Experiment. See :func:`callbacks.bases.lambda_callback` for more information

        Notes
        -----
        Overriding default kwargs at "environment_params_path": If you have any of the above kwargs specified in the .json file
        at environment_params_path (except environment_params_path, which will be ignored), you can override its value by
        passing it as a kwarg when initializing :class:`Environment`. The contents at environment_params_path are only used when
        the matching kwarg supplied at initialization is None. See the "Examples" section below for details.

        The order of precedence for determining the value of each parameter is as follows, with items at the top having the
        highest priority, and deferring only to the items below if their own value is None:
        - 1)kwargs passed directly to :meth:`Environment.__init__` on initialization,
        - 2)keys of the file at environment_params_path (if valid .json object),
        - 3)keys of the DEFAULT_PARAMS dict

        Examples
        --------
        TODO: ADD EXAMPLE FOR OVERRIDING PARAMS WITH KWARGS AND THE ORDER OF PRECEDENCE, AS IN THE FIRST TWO NOTES
        """
        G.Env = self
        self.environment_params_path = environment_params_path
        self.root_results_path = root_results_path

        #################### Attributes Used by Experiments ####################
        self.train_dataset = train_dataset
        self.holdout_dataset = holdout_dataset
        self.test_dataset = test_dataset

        self.target_column = target_column
        self.id_column = id_column
        self.do_predict_proba = do_predict_proba
        self.prediction_formatter = prediction_formatter
        self.metrics_map = metrics_map
        self.metrics_params = metrics_params

        self.cross_experiment_params = dict()
        self.cross_validation_type = cross_validation_type
        self.runs = runs
        self.global_random_seed = global_random_seed
        self.random_seeds = random_seeds
        self.random_seed_bounds = random_seed_bounds
        self.cross_validation_params = cross_validation_params

        #################### Ancillary Environment Settings ####################
        self.verbose = verbose
        self.file_blacklist = file_blacklist
        self.reporting_handler_params = reporting_handler_params or {}
        self.to_csv_params = to_csv_params or {}
        self.do_full_save = do_full_save
        self.experiment_callbacks = experiment_callbacks or []

        self.result_paths = {
            'root': self.root_results_path,
            'checkpoint': None,
            'description': None,
            'heartbeat': None,
            'predictions_holdout': None,
            'predictions_in_fold': None,
            'predictions_oof': None,
            'predictions_test': None,
            'script_backup': None,
            'tested_keys': None,
            'key_attribute_lookup': None,
            'leaderboards': None,
            'global_leaderboard': None,
        }

        self.current_task = None
        self.cross_experiment_key = None

        self.environment_workflow()

    def __repr__(self):
        return F'{self.__class__.__name__}(cross_experiment_key={self.cross_experiment_key!s})'

    def __eq__(self, other):
        return self.cross_experiment_key == other

    # def __enter__(self):
    #     pass

    # def __exit__(self):
    #     G.reset_attributes()

    def environment_workflow(self):
        """Execute all methods required to validate the environment and run Experiments"""
        self.update_custom_environment_params()
        self.validate_parameters()
        self.define_holdout_set()
        self.format_result_paths()
        self.generate_cross_experiment_key()
        G.log('Cross-Experiment Key: {!s}'.format(self.cross_experiment_key))

    def validate_parameters(self):
        """Ensure the provided parameters are valid and properly formatted"""
        #################### root_results_path ####################
        if self.root_results_path is None:
            G.warn('Received root_results_path=None. Results will not be stored at all.')
        elif isinstance(self.root_results_path, str):
            if not self.root_results_path.endswith(ASSETS_DIRNAME):
                self.root_results_path = os.path.join(self.root_results_path, ASSETS_DIRNAME)
                self.result_paths['root'] = self.root_results_path
            if not os.path.exists(self.root_results_path):
                os.makedirs(self.root_results_path, exist_ok=True)
        else:
            raise TypeError('root_results_path must be None or str, not {}: {}'.format(*type_val(self.root_results_path)))

        #################### verbose ####################
        if not isinstance(self.verbose, bool):
            raise TypeError('verbose must be a boolean. Received {}: {}'.format(*type_val(self.verbose)))

        #################### file_blacklist ####################
        self.file_blacklist = validate_file_blacklist(self.file_blacklist)

        #################### Train/Test Datasets ####################
        if isinstance(self.train_dataset, str):
            self.train_dataset = pd.read_csv(self.train_dataset)
        if isinstance(self.test_dataset, str):
            self.test_dataset = pd.read_csv(self.test_dataset)

        #################### metrics_params/metrics_map ####################
        if (self.metrics_map is not None) and ('metrics_map' in self.metrics_params.keys()):
            raise ValueError(
                '`metrics_map` may be provided as a kwarg, or as a key in `metrics_params`, but NOT BOTH. Received: ' +
                F'\n `metrics_map`={self.metrics_map}\n `metrics_params`={self.metrics_params}'
            )
        else:
            if self.metrics_map is None:
                self.metrics_map = self.metrics_params['metrics_map']
            self.metrics_params = {**dict(metrics_map=self.metrics_map), **self.metrics_params}

        #################### to_csv_params ####################
        self.to_csv_params = {_k: _v for _k, _v in self.to_csv_params.items() if _k != 'path_or_buf'}

        #################### cross_experiment_params ####################
        self.cross_experiment_params = dict(
            cross_validation_type=self.cross_validation_type,
            runs=self.runs,
            global_random_seed=self.global_random_seed,
            random_seeds=self.random_seeds,
            random_seed_bounds=self.random_seed_bounds,
        )

        #################### experiment_callbacks ####################
        if not isinstance(self.experiment_callbacks, list):
            self.experiment_callbacks = [self.experiment_callbacks]
        for callback in self.experiment_callbacks:
            if not isclass(callback):
                raise TypeError(F'experiment_callbacks must be classes. Received {type(callback)}: {callback}')
            if callback.__name__ != 'LambdaCallback':
                raise ValueError(F'experiment_callbacks must be LambdaCallback instances, not {callback.__name__}: {callback}')

    def define_holdout_set(self):
        """Define :attr:`Environment.holdout_dataset`, and (if holdout_dataset is callable), also modifies train_dataset"""
        if callable(self.holdout_dataset):
            self.train_dataset, self.holdout_dataset = self.holdout_dataset(self.train_dataset, self.target_column)
        elif isinstance(self.holdout_dataset, str):
            try:
                self.holdout_dataset = pd.read_csv(self.holdout_dataset)
            except FileNotFoundError:
                raise
        elif (self.holdout_dataset is not None) and (not isinstance(self.holdout_dataset, pd.DataFrame)):
            raise TypeError(F'holdout_dataset must be one of: [None, DataFrame, callable, str], not {type(self.holdout_dataset)}')

        if (self.holdout_dataset is not None) and (not np.array_equal(self.train_dataset.columns, self.holdout_dataset.columns)):
            raise ValueError('\n'.join([
                'train_dataset and holdout_dataset must have the same columns. Instead, '
                F'train_dataset had {len(self.train_dataset.columns)} columns: {self.train_dataset.columns}',
                F'holdout_dataset had {len(self.holdout_dataset.columns)} columns: {self.holdout_dataset.columns}',
            ]))

    def format_result_paths(self):
        """Remove paths contained in file_blacklist, and format others to prepare for saving results"""
        if self.file_blacklist == 'ALL':
            return

        if self.root_results_path is not None:
            # Blacklist prediction files for datasets not given
            if self.holdout_dataset is None:
                self.file_blacklist.append('predictions_holdout')
            if self.test_dataset is None:
                self.file_blacklist.append('predictions_test')

            for k in self.result_paths.keys():
                if k == 'root':
                    continue
                elif k not in self.file_blacklist:
                    self.result_paths[k] = os.path.join(self.root_results_path, RESULT_FILE_SUB_DIR_PATHS[k])
                else:
                    self.result_paths[k] = None
                    # G.debug('Result file "{}" has been blacklisted'.format(k))

    def update_custom_environment_params(self):
        """Try to update null parameters from environment_params_path, or DEFAULT_PARAMS"""
        allowed_parameter_keys = [k for k, v in signature(Environment).parameters.items() if v.kind == v.KEYWORD_ONLY]
        user_defaults = {}

        if (not isinstance(self.environment_params_path, str)) and (self.environment_params_path is not None):
            raise TypeError('environment_params_path must be a str, not {}: {}'.format(*type_val(self.environment_params_path)))

        try:
            user_defaults = read_json(self.environment_params_path)
        except TypeError:
            if self.environment_params_path is not None:
                raise
        except FileNotFoundError:
            raise

        if not isinstance(user_defaults, dict):
            raise TypeError('environment_params_path must contain a dict. Received {}: {}'.format(*type_val(user_defaults)))

        #################### Check user_defaults ####################
        for k, v in user_defaults.items():
            if k not in allowed_parameter_keys:
                G.warn('\n\t'.join([
                    'Warning: Invalid key ("{}") in user-defined default Environment parameter file at "{}"',
                    'If "{}" is expected to do something, it really won\'t, so it is recommended that it be removed or fixed.',
                    'The following are valid default keys: {}'
                ]).format(k, self.environment_params_path, k, allowed_parameter_keys))
            elif getattr(self, k) is None:
                setattr(self, k, v)
                G.debug('Environment kwarg "{}" was set to user default at "{}"'.format(k, self.environment_params_path))

        #################### Check Module Default Environment Arguments ####################
        for k in allowed_parameter_keys:
            if getattr(self, k) is None:
                setattr(self, k, self.DEFAULT_PARAMS.get(k, None))

    def generate_cross_experiment_key(self):
        """Generate a key to describe the current Environment's cross-experiment parameters"""
        parameters = dict(
            metrics_params=self.metrics_params,
            cross_validation_params=self.cross_validation_params,
            target_column=self.target_column,
            id_column=self.id_column,
            do_predict_proba=self.do_predict_proba,
            prediction_formatter=self.prediction_formatter,
            train_dataset=self.train_dataset,
            test_dataset=self.test_dataset,
            holdout_dataset=self.holdout_dataset,
            cross_experiment_params=self.cross_experiment_params,
            to_csv_params=self.to_csv_params,
        )
        self.cross_experiment_key = CrossExperimentKeyMaker(parameters)

    def initialize_reporting(self):
        """Initialize reporting for the Environment and all experiments conducted during its lifetime"""
        reporting_handler_params = self.reporting_handler_params
        reporting_handler_params['heartbeat_path'] = '{}/Heartbeat.log'.format(self.root_results_path)
        reporting_handler = ReportingHandler(**reporting_handler_params)

        #################### Make Unified Logging Globally Available ####################
        G.log = reporting_handler.log
        G.debug = reporting_handler.debug
        G.warn = reporting_handler.warn


def validate_file_blacklist(blacklist):
    """Validate contents of blacklist. For most values, the corresponding file is saved upon completion of the experiment. See
    the "Notes" section below for details on some special cases

    Parameters
    ----------
    blacklist: List of strings, or None
        The result files that should not be saved

    Returns
    -------
    blacklist: List
        If not empty, acceptable list of result file types to blacklist

    Notes
    -----
    'heartbeat': If the heartbeat file is saved, a new file is not generated and saved to the "Experiments/Heartbeats" directory
    as is the case with most other files. Instead, the general "Heartbeat.log" file is copied and renamed to the current
    experiment id, then saved to the appropriate dir. This is because the general "Heartbeat.log" file represents the heartbeat
    for whatever experiment is currently in progress.

    'script_backup': This file is saved as quickly as possible after starting a new experiment, rather than waiting for the
    experiment to end. There are two reasons for this behavior: 1) to avoid saving any changes that may have been made to a file
    after it has been executed, and 2) to have the offending file in the event of a catastrophic failure that results in no other
    files being saved.

    'description' and 'tested_keys': These two results types constitute a bare minimum of sorts for experiment recording. If
    either of these two are blacklisted, then as far as the library is concerned, the experiment never took place.

    'tested_keys' (continued): If this string is included in the blacklist, then the contents of the "KeyAttributeLookup"
    directory will also be excluded from the list of files to update"""
    valid_values = [
        # 'checkpoint',
        'description',
        'heartbeat',
        'predictions_holdout',
        'predictions_in_fold',
        'predictions_oof',
        'predictions_test',
        'script_backup',
        'tested_keys',
    ]
    if blacklist == 'ALL':
        G.warn('WARNING: Received `blacklist`="ALL". Nothing will be saved')
        return blacklist

    if not blacklist:
        return []
    elif not isinstance(blacklist, list):
        raise TypeError('Expected blacklist to be a list, but received {}: {}'.format(type(blacklist), blacklist))
    elif not all([isinstance(_, str) for _ in blacklist]):
        invalid_files = [(type(_).__name__, _) for _ in blacklist if not isinstance(_, str)]
        raise TypeError('Expected contents of blacklist to be strings, but received {}'.format(invalid_files))

    for a_file in blacklist:
        if a_file not in valid_values:
            raise ValueError('Received invalid blacklist value: {}.\nExpected one of: [{}]'.format(a_file, valid_values))
        if a_file in ['description', 'tested_keys']:
            G.warn(F'Including {a_file!r} in file_blacklist will severely impede the functionality of this library')

    return blacklist


def _execute():
    # invalid_blacklist = ['foo', 'bar', 14, {'a': 10, 'b': 20}]
    # validate_file_blacklist(invalid_blacklist)
    pass


if __name__ == '__main__':
    _execute()
